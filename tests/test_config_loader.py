"""Tests for infra/config_loader.py.

Five categories:
1. Happy path — valid config loads correctly
2. Boundary/edge cases — no required_fields, dict value, non-string types
3. Graceful degradation — missing file, invalid JSON
4. Bad input/validation — missing required field, empty required field
5. Idempotency/state — ENV_CONFIG_PATH override, explicit path overrides env var,
   relative fallback path
"""

import json
import os
import pytest

from agent_shared.infra.config_loader import ConfigValidationError, load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_json(path, data):
    """Write a dict as JSON to the given Path."""
    path.write_text(json.dumps(data), encoding="utf-8")


SAMPLE_CONFIG = {
    "trello_api_key": "test_key",
    "trello_api_token": "test_token",
    "trello_board_id": "oNIV6Mcq",
    "ollama_host": "http://localhost:11434",
    "ollama_model": "qwen3:8b",
    "anthropic_api_keys": {
        "gmail-to-trello": "sk-ant-test-gmail-key",
    },
}


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_load_config_valid_returns_dict(tmp_path):
    """Valid config file loads correctly and returns a plain dict."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    result = load_config(config_path=str(cfg_file))

    assert isinstance(result, dict)
    assert result["trello_api_key"] == "test_key"
    assert result["trello_board_id"] == "oNIV6Mcq"
    assert result["anthropic_api_keys"]["gmail-to-trello"] == "sk-ant-test-gmail-key"


def test_load_config_required_fields_all_present(tmp_path):
    """Required fields validation passes when all fields are present and non-empty."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    result = load_config(
        required_fields=["trello_api_key", "trello_api_token"],
        config_path=str(cfg_file),
    )

    assert result["trello_api_key"] == "test_key"


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_load_config_no_required_fields_loads_all(tmp_path):
    """When required_fields is None, all fields are loaded without validation."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    result = load_config(config_path=str(cfg_file))

    assert len(result) == len(SAMPLE_CONFIG)


def test_load_config_required_fields_empty_list(tmp_path):
    """Empty required_fields list performs no validation."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    result = load_config(required_fields=[], config_path=str(cfg_file))

    assert isinstance(result, dict)


def test_load_config_dict_value_is_valid(tmp_path):
    """A non-string required field (dict) that is non-empty passes validation."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    # anthropic_api_keys is a dict — it should not raise
    result = load_config(
        required_fields=["anthropic_api_keys"],
        config_path=str(cfg_file),
    )

    assert isinstance(result["anthropic_api_keys"], dict)


def test_load_config_integer_zero_passes_validation(tmp_path):
    """An integer value of 0 is considered non-empty (valid) by validation."""
    data = {"retry_count": 0, "name": "agent"}
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, data)

    # retry_count=0 is a meaningful value, not "empty"
    result = load_config(required_fields=["retry_count"], config_path=str(cfg_file))

    assert result["retry_count"] == 0


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------

def test_load_config_missing_file_raises_file_not_found(tmp_path):
    """FileNotFoundError raised when the config file does not exist."""
    missing = tmp_path / "nonexistent.json"

    with pytest.raises(FileNotFoundError):
        load_config(config_path=str(missing))


def test_load_config_invalid_json_raises_json_decode_error(tmp_path):
    """json.JSONDecodeError raised when the file contains invalid JSON."""
    cfg_file = tmp_path / ".env.json"
    cfg_file.write_text("{ not valid json !!!", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_config(config_path=str(cfg_file))


# ---------------------------------------------------------------------------
# 4. Bad input / validation
# ---------------------------------------------------------------------------

def test_load_config_missing_required_field_raises_error(tmp_path):
    """ConfigValidationError raised when a required field is absent from config."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, {"trello_api_key": "key"})  # missing trello_api_token

    with pytest.raises(ConfigValidationError, match="trello_api_token"):
        load_config(
            required_fields=["trello_api_key", "trello_api_token"],
            config_path=str(cfg_file),
        )


def test_load_config_empty_string_required_field_raises_error(tmp_path):
    """ConfigValidationError raised when a required field is an empty string."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, {"trello_api_key": "", "trello_api_token": "tok"})

    with pytest.raises(ConfigValidationError, match="trello_api_key"):
        load_config(
            required_fields=["trello_api_key"],
            config_path=str(cfg_file),
        )


def test_load_config_none_required_field_raises_error(tmp_path):
    """ConfigValidationError raised when a required field is null/None."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, {"trello_api_key": None})

    with pytest.raises(ConfigValidationError, match="trello_api_key"):
        load_config(
            required_fields=["trello_api_key"],
            config_path=str(cfg_file),
        )


# ---------------------------------------------------------------------------
# 5. Idempotency / state — path resolution
# ---------------------------------------------------------------------------

def test_load_config_env_config_path_override(tmp_path, monkeypatch):
    """ENV_CONFIG_PATH environment variable is used when no config_path given."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)
    monkeypatch.setenv("ENV_CONFIG_PATH", str(cfg_file))

    result = load_config()

    assert result["trello_api_key"] == "test_key"


def test_load_config_explicit_path_overrides_env_var(tmp_path, monkeypatch):
    """Explicit config_path parameter takes priority over ENV_CONFIG_PATH."""
    env_cfg = tmp_path / "env.json"
    write_json(env_cfg, {"source": "env_var"})

    explicit_cfg = tmp_path / "explicit.json"
    write_json(explicit_cfg, {"source": "explicit_param"})

    monkeypatch.setenv("ENV_CONFIG_PATH", str(env_cfg))

    result = load_config(config_path=str(explicit_cfg))

    assert result["source"] == "explicit_param"


def test_load_config_relative_fallback_path(tmp_path, monkeypatch):
    """Fallback to ../config/.env.json relative to cwd when no other path given."""
    # Create directory structure: tmp_path/agent/ (cwd) and tmp_path/config/.env.json
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cfg_file = config_dir / ".env.json"
    write_json(cfg_file, {"source": "fallback", "key": "value"})

    monkeypatch.delenv("ENV_CONFIG_PATH", raising=False)
    monkeypatch.chdir(agent_dir)

    result = load_config()

    assert result["source"] == "fallback"


def test_load_config_called_twice_same_file_returns_same_data(tmp_path):
    """Calling load_config twice on the same file returns identical dicts (no caching quirks)."""
    cfg_file = tmp_path / ".env.json"
    write_json(cfg_file, SAMPLE_CONFIG)

    result1 = load_config(config_path=str(cfg_file))
    result2 = load_config(config_path=str(cfg_file))

    assert result1 == result2
    assert result1 is not result2  # fresh dict each time, not a cached reference
