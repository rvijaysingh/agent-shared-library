"""Tests for infra/db.py.

Five categories:
1. Happy path — connection created, WAL mode, row_factory, table ops
2. Boundary/edge cases — empty table name check, idempotent ensure_table
3. Graceful degradation — context manager rollback on exception
4. Bad input/validation — table_exists returns False for missing table
5. Idempotency/state — ensure_table twice doesn't error, connection always closed
"""

import sqlite3
import pytest

from agent_shared.infra.db import (
    db_connection,
    ensure_table,
    get_db_connection,
    table_exists,
)


CREATE_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value TEXT
)
"""


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_get_db_connection_returns_connection(tmp_path):
    """get_db_connection returns a valid sqlite3.Connection."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_get_db_connection_wal_mode_enabled(tmp_path):
    """WAL journal mode is enabled on the returned connection."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
    finally:
        conn.close()


def test_get_db_connection_foreign_keys_enabled(tmp_path):
    """Foreign key enforcement is enabled on the returned connection."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_get_db_connection_row_factory_is_sqlite_row(tmp_path):
    """Row factory is set to sqlite3.Row for dict-like column access."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        row = conn.execute("SELECT x FROM t").fetchone()
        # sqlite3.Row allows column access by name
        assert row["x"] == 42
    finally:
        conn.close()


def test_table_exists_returns_true_for_existing_table(tmp_path):
    """table_exists returns True after CREATE TABLE."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        assert table_exists(conn, "items") is True
    finally:
        conn.close()


def test_ensure_table_creates_table(tmp_path):
    """ensure_table executes CREATE TABLE IF NOT EXISTS and the table appears."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        ensure_table(conn, CREATE_ITEMS_SQL)
        assert table_exists(conn, "items") is True
    finally:
        conn.close()


def test_ensure_table_allows_insert_after_creation(tmp_path):
    """A table created via ensure_table accepts INSERT statements."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        ensure_table(conn, CREATE_ITEMS_SQL)
        conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("foo", "bar"))
        conn.commit()
        row = conn.execute("SELECT name, value FROM items").fetchone()
        assert row["name"] == "foo"
        assert row["value"] == "bar"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_table_exists_returns_false_for_missing_table(tmp_path):
    """table_exists returns False when the table has not been created."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        assert table_exists(conn, "nonexistent_table") is False
    finally:
        conn.close()


def test_ensure_table_is_idempotent(tmp_path):
    """Calling ensure_table twice with the same SQL does not raise an error."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        ensure_table(conn, CREATE_ITEMS_SQL)
        ensure_table(conn, CREATE_ITEMS_SQL)  # second call must not raise
        assert table_exists(conn, "items") is True
    finally:
        conn.close()


def test_get_db_connection_creates_parent_directories(tmp_path):
    """Parent directories of the DB path are created automatically."""
    db_file = tmp_path / "subdir" / "nested" / "data.db"
    conn = get_db_connection(str(db_file))
    try:
        assert db_file.exists()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------

def test_db_connection_rolls_back_on_exception(tmp_path):
    """db_connection rolls back the transaction when an exception is raised."""
    db_file = tmp_path / "test.db"

    # Set up table first
    with db_connection(str(db_file)) as conn:
        ensure_table(conn, CREATE_ITEMS_SQL)

    # Insert inside a failing context — should be rolled back
    with pytest.raises(ValueError):
        with db_connection(str(db_file)) as conn:
            conn.execute("INSERT INTO items (name) VALUES (?)", ("should_rollback",))
            raise ValueError("simulated failure")

    # Verify the insert was rolled back
    verify_conn = get_db_connection(str(db_file))
    try:
        rows = verify_conn.execute("SELECT * FROM items").fetchall()
        assert len(rows) == 0
    finally:
        verify_conn.close()


def test_db_connection_re_raises_exception(tmp_path):
    """db_connection re-raises the original exception after rolling back."""
    db_file = tmp_path / "test.db"

    with pytest.raises(RuntimeError, match="boom"):
        with db_connection(str(db_file)) as conn:
            raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# 4. Bad input / validation (table_exists False, CHECK constraints)
# ---------------------------------------------------------------------------

def test_table_exists_case_sensitive(tmp_path):
    """table_exists is case-sensitive; 'Items' != 'items' in sqlite_master."""
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        conn.execute("CREATE TABLE items (id INTEGER)")
        assert table_exists(conn, "items") is True
        assert table_exists(conn, "Items") is False
    finally:
        conn.close()


def test_check_constraint_validated_at_insert_not_create(tmp_path):
    """
    SQLite CHECK constraints fire at INSERT, not CREATE TABLE.
    (Documents the LESSONS.md known behavior.)
    """
    db_file = tmp_path / "test.db"
    conn = get_db_connection(str(db_file))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS statuses (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('ok', 'fail'))
            )
        """)
        conn.commit()

        # Valid insert — should not raise
        conn.execute("INSERT INTO statuses (status) VALUES (?)", ("ok",))
        conn.commit()

        # Invalid insert — should raise IntegrityError at INSERT time
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO statuses (status) VALUES (?)", ("invalid",))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Idempotency / state — context manager lifecycle
# ---------------------------------------------------------------------------

def test_db_connection_commits_on_success(tmp_path):
    """db_connection commits the transaction on clean exit."""
    db_file = tmp_path / "test.db"

    with db_connection(str(db_file)) as conn:
        ensure_table(conn, CREATE_ITEMS_SQL)
        conn.execute("INSERT INTO items (name) VALUES (?)", ("committed",))

    # Open a fresh connection to verify the row was committed
    verify_conn = get_db_connection(str(db_file))
    try:
        row = verify_conn.execute("SELECT name FROM items WHERE name='committed'").fetchone()
        assert row is not None
        assert row["name"] == "committed"
    finally:
        verify_conn.close()


def test_db_connection_closes_connection_after_success(tmp_path):
    """The connection is closed after the context manager exits cleanly."""
    db_file = tmp_path / "test.db"
    captured_conn = None

    with db_connection(str(db_file)) as conn:
        captured_conn = conn

    # Attempting to use the connection after context exit should fail
    with pytest.raises(Exception):
        captured_conn.execute("SELECT 1")


def test_db_connection_closes_connection_after_exception(tmp_path):
    """The connection is closed even when an exception is raised inside."""
    db_file = tmp_path / "test.db"
    captured_conn = None

    with pytest.raises(ValueError):
        with db_connection(str(db_file)) as conn:
            captured_conn = conn
            raise ValueError("deliberate")

    with pytest.raises(Exception):
        captured_conn.execute("SELECT 1")
