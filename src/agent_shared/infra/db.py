"""
SQLite connection factory and schema utilities.

Provides: get_db_connection, table_exists, ensure_table, db_connection context manager.
WAL mode and foreign keys enabled by default. The caller owns the db_path.
No DB path is hardcoded here — everything is passed as parameters.

NOTE: SQLite CHECK constraints are validated at INSERT time, not CREATE TABLE time.
Always test schema correctness with actual INSERT statements (see LESSONS.md).
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """
    Create a SQLite connection with WAL mode and foreign keys enabled.

    Creates parent directories and the DB file if they don't exist.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        sqlite3.Connection with row_factory = sqlite3.Row, WAL mode, and
        foreign keys enabled.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    logger.debug("Opening DB connection: %s", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """
    Check if a table exists in the database.

    Args:
        conn: An open SQLite connection.
        table_name: The table name to check.

    Returns:
        True if the table exists, False otherwise.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def ensure_table(conn: sqlite3.Connection, create_sql: str) -> None:
    """
    Execute a CREATE TABLE IF NOT EXISTS statement.

    The caller provides the full SQL, including the table name and schema.
    This function does not generate SQL — it only executes what is given.

    Args:
        conn: An open SQLite connection.
        create_sql: Full CREATE TABLE IF NOT EXISTS SQL statement.
    """
    conn.execute(create_sql)
    conn.commit()


@contextmanager
def db_connection(db_path: str):
    """
    Context manager that yields a connection and commits on success,
    rolls back on exception, and always closes.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Yields:
        sqlite3.Connection configured with WAL mode, foreign keys, and
        sqlite3.Row row_factory.
    """
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
        logger.debug("DB transaction committed: %s", db_path)
    except Exception:
        conn.rollback()
        logger.debug("DB transaction rolled back: %s", db_path)
        raise
    finally:
        conn.close()
        logger.debug("DB connection closed: %s", db_path)
