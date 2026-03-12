"""
SQLite connection factory and schema utilities.

Provides: get_db_connection, table_exists, ensure_table, db_connection context manager.
WAL mode and foreign keys enabled by default. The caller owns the db_path.
No DB path is hardcoded here — everything is passed as parameters.
"""

# TODO: Implement get_db_connection, table_exists, ensure_table, db_connection (Phase 2)
