"""
Global configuration loader.

Reads the global .env.json and validates required fields. This is the ONLY
module in agent_shared that reads from the filesystem for config. All other
modules receive config as function/constructor parameters.

Path resolution order:
1. config_path parameter (if provided)
2. ENV_CONFIG_PATH environment variable
3. ../config/.env.json relative to os.getcwd()
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when required config fields are missing or empty."""
    pass


def load_config(
    required_fields: list[str] | None = None,
    config_path: str | None = None,
) -> dict:
    """
    Load global .env.json and validate required fields.

    Resolution order for config path:
    1. config_path parameter (if provided)
    2. ENV_CONFIG_PATH environment variable
    3. ../config/.env.json relative to caller's working directory (os.getcwd())

    Args:
        required_fields: List of top-level keys that must be present and
            non-empty in the loaded config. If None or empty, no validation
            is performed beyond parsing the JSON.
        config_path: Explicit path to the .env.json file. Highest priority.

    Returns:
        Plain dict of all config key-value pairs.

    Raises:
        ConfigValidationError: If any required field is missing or empty.
        FileNotFoundError: If the config file is not found at any resolved path.
        json.JSONDecodeError: If the config file contains invalid JSON.
    """
    resolved_path = _resolve_config_path(config_path)
    logger.info("Loading config from %s", resolved_path)

    if not resolved_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {resolved_path}"
        )

    with resolved_path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise json.JSONDecodeError(
            f"Config must be a JSON object, got {type(data).__name__}",
            doc="",
            pos=0,
        )

    if required_fields:
        _validate_required_fields(data, required_fields, str(resolved_path))

    logger.info("Config loaded successfully (%d fields)", len(data))
    return data


def _resolve_config_path(config_path: str | None) -> Path:
    """Resolve the config file path using the priority order.

    Args:
        config_path: Explicit override path, or None to use env var / fallback.

    Returns:
        Resolved Path object.
    """
    if config_path is not None:
        return Path(config_path)

    env_var = os.environ.get("ENV_CONFIG_PATH")
    if env_var:
        logger.debug("Using ENV_CONFIG_PATH: %s", env_var)
        return Path(env_var)

    fallback = Path(os.getcwd()) / ".." / "config" / ".env.json"
    logger.debug("Using fallback config path: %s", fallback)
    return fallback


def _validate_required_fields(data: dict, required_fields: list[str], source: str) -> None:
    """Check that each required field is present and non-empty.

    Args:
        data: The parsed config dict.
        required_fields: Keys that must exist and be non-empty.
        source: Config file path for error messages.

    Raises:
        ConfigValidationError: On the first missing or empty field found.
    """
    for field in required_fields:
        if field not in data:
            raise ConfigValidationError(
                f"Required field '{field}' is missing from config at {source}"
            )
        value = data[field]
        # Reject None and empty strings; 0 and False are valid non-empty values.
        if value is None or value == "":
            raise ConfigValidationError(
                f"Required field '{field}' is empty in config at {source}"
            )
