"""
agent_shared.infra — Infrastructure utilities.

Re-exports: load_config, setup_logging, get_db_connection

Covers: global config loading (.env.json), rotating file logger factory,
and SQLite connection factory with WAL mode and context manager support.
"""

# Re-exports will be added when source logic is implemented.
# from agent_shared.infra.config_loader import load_config, ConfigValidationError
# from agent_shared.infra.logging_setup import setup_logging
# from agent_shared.infra.db import get_db_connection, table_exists, ensure_table, db_connection
