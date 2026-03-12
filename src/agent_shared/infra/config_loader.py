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

# TODO: Implement load_config, ConfigValidationError (Phase 2)
