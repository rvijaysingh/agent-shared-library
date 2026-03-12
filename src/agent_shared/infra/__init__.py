"""
agent_shared.infra — Infrastructure utilities.

Re-exports: load_config, ConfigValidationError, setup_logging,
get_db_connection, table_exists, ensure_table, db_connection

Covers: global config loading (.env.json), rotating file logger factory,
and SQLite connection factory with WAL mode and context manager support.
"""

from agent_shared.infra.config_loader import ConfigValidationError, load_config
from agent_shared.infra.db import db_connection, ensure_table, get_db_connection, table_exists
from agent_shared.infra.logging_setup import setup_logging

__all__ = [
    "load_config",
    "ConfigValidationError",
    "setup_logging",
    "get_db_connection",
    "table_exists",
    "ensure_table",
    "db_connection",
]
