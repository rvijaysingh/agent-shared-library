# Migration Guide — gmail-to-trello Agent to agent-shared

This document describes how to migrate the gmail-to-trello agent from its current self-contained
implementation to use `agent-shared`. Migration is done in phases, each independently testable
and independently rollbackable. The gmail-to-trello agent's existing 197 tests are the acceptance
criteria — they must all pass after each phase.

---

## Pre-Migration Checklist (CRITICAL — do before Phase 1)

Before writing any code, complete these steps:

1. **Add `anthropic_api_keys` dict to global `.env.json`**:
   The gmail-to-trello agent currently stores its Anthropic API key as a top-level string in
   `agent_config.json`. The shared library expects a `anthropic_api_keys` dict in `.env.json`.

   Old `agent_config.json`:
   ```json
   { "anthropic_api_key": "sk-ant-..." }
   ```

   New `.env.json` (add this entry):
   ```json
   {
     "trello_api_key": "...",
     "trello_api_token": "...",
     "trello_board_id": "oNIV6Mcq",
     "anthropic_api_keys": {
       "gmail-to-trello": "sk-ant-..."
     }
   }
   ```

2. **Install agent-shared into the agent's virtualenv**:
   ```bash
   cd gmail-to-trello
   pip install -e ../agent-shared-library
   ```

3. **Run the existing test suite** to establish a green baseline:
   ```bash
   cd gmail-to-trello
   pytest tests/ -x
   ```
   All tests must pass before starting migration.

4. **Set `ENV_CONFIG_PATH`** to point to the global `.env.json`:
   ```powershell
   $env:ENV_CONFIG_PATH = "C:\Users\devon\config\.env.json"
   ```

---

## Migration Phases

### Phase 1: Migrate `infra/config_loader.py`

**What changes**:
- Remove the local `config_loader.py` (or its equivalent in the agent).
- Replace `from config_loader import load_config, ConfigError` with
  `from agent_shared.infra import load_config, ConfigValidationError`.
- Update the agent's startup code to call `load_config(required_fields=[...])`.

**Key differences from the reference implementation**:

| Aspect | Old (agent's config_loader) | New (agent-shared) |
|--------|---------------------------|-------------------|
| Exception class | `ConfigError` | `ConfigValidationError` |
| Return type | Typed dataclass tuple `(GlobalConfig, AgentConfig)` | Plain `dict` |
| Param name | `env_config_path` | `config_path` |
| Field access | `config.global_config.trello_api_key` | `config["trello_api_key"]` |
| Anthropic key | `config.agent_config.anthropic_api_key` | `config["anthropic_api_keys"]["gmail-to-trello"]` |

**Update the agent's startup**:
```python
# Old
from config_loader import load_config, ConfigError
try:
    global_cfg, agent_cfg = load_config()
    trello_key = global_cfg.trello_api_key
    anthropic_key = agent_cfg.anthropic_api_key
except ConfigError as e:
    ...

# New
from agent_shared.infra import load_config, ConfigValidationError
try:
    config = load_config(
        required_fields=["trello_api_key", "trello_api_token", "trello_board_id",
                         "anthropic_api_keys"],
    )
    trello_key = config["trello_api_key"]
    anthropic_key = config["anthropic_api_keys"]["gmail-to-trello"]
except ConfigValidationError as e:
    ...
```

**Mock target changes for tests**:
- Old: `patch("config_loader.load_config")` or `patch("agent.config_loader.load_config")`
- New: `patch("agent_shared.infra.config_loader.load_config")`

**What to test**: Run all config-related tests. Verify ConfigValidationError is raised in the
same situations where ConfigError was raised.

**Rollback**: Revert the import changes. No data migration required.

---

### Phase 2: Migrate `infra/logging_setup.py`

**What changes**:
- Replace the local logging setup with `from agent_shared.infra import setup_logging`.
- `setup_logging(log_path, logger_name)` signature is the same or simpler — no param name
  changes expected.

**Key differences**:
- The shared library version clears existing handlers before adding the new one. This is
  intentional and matches LESSONS.md guidance.
- The shared library does NOT add a StreamHandler. If the agent wants console output, it must
  add its own.

**What to test**: Run logging-related tests. Verify log files are created in expected locations.

**Rollback**: Revert the import changes.

---

### Phase 3: Migrate `infra/db.py`

**What changes**:
- Remove the local `db.py` (or equivalent).
- Replace `from db import init_db, insert_record, check_duplicate` with
  `from agent_shared.infra import get_db_connection, ensure_table, db_connection`.
- The shared library provides lower-level primitives. The agent must supply its own SQL.

**Key differences**:

| Old function | New equivalent |
|-------------|----------------|
| `init_db(db_path)` | `get_db_connection(db_path)` + `ensure_table(conn, create_sql)` |
| `insert_record(conn, gmail_id, card_id, card_url)` | `conn.execute("INSERT INTO ...", (gmail_id, card_id, card_url))` |
| `check_duplicate(conn, gmail_id)` | `conn.execute("SELECT 1 FROM ... WHERE gmail_id=?", (gmail_id,)).fetchone() is not None` |

**The agent must provide the CREATE TABLE SQL**:
```python
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id TEXT NOT NULL UNIQUE,
    card_id TEXT NOT NULL,
    card_url TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

conn = get_db_connection(str(db_path))
ensure_table(conn, CREATE_TABLE_SQL)
```

**Mock target changes for tests**:
- Old: `patch("db.sqlite3.connect")` or `patch("agent.db.init_db")`
- New: `patch("agent_shared.infra.db.sqlite3.connect")` or use a real SQLite with `tmp_path`

**What to test**: Run all database-related tests. Verify processed emails are correctly written
and that the duplicate check correctly prevents double-processing.

**Rollback**: Revert the import changes. The database schema is unchanged.

---

### Phase 4: Migrate `trello/client.py`

**What changes**:
- Remove the local `trello_client.py`.
- Replace `from trello_client import create_card` with
  `from agent_shared.trello import TrelloClient`.
- Instantiate a `TrelloClient` at startup.

**Key differences**:

| Aspect | Old (gmail-to-trello) | New (agent-shared) |
|--------|----------------------|-------------------|
| Interface | Module-level function with explicit key/token params per call | `TrelloClient` class instantiated once with credentials |
| `create_card` signature | `create_card(api_key, api_token, list_id, name, description)` | `client.create_card(list_id, name, description)` |
| Return type | `(card_id, card_url)` tuple | `dict` with `"id"` and `"url"` keys |
| Orchestrator access | `card_id, card_url = create_card(...)` | `result = client.create_card(...); result["id"], result["url"]` |

**Update the agent's orchestrator**:
```python
# Old
from trello_client import create_card
card_id, card_url = create_card(api_key, api_token, list_id, name, description)

# New
from agent_shared.trello import TrelloClient
client = TrelloClient(api_key=..., api_token=..., board_id=...)
result = client.create_card(list_id, name, description)
card_id = result["id"]
card_url = result["url"]
```

**Mock target changes for tests**:
- Old: `patch("trello_client.requests.post")` (or wherever the old client made HTTP calls)
- New: `patch("requests.request", return_value=make_response(200, {...}))` — the shared client
  uses `requests.request` for all methods.

**What to test**: Run all Trello integration tests. Verify that `card_id` and `card_url` are
correctly extracted from the dict return value in the orchestrator.

**Rollback**: Revert the import and calling-code changes.

---

### Phase 5: Migrate `llm/client.py`

**What changes**:
- Remove the local LLM client module.
- Replace the local inference function with `from agent_shared.llm import LLMClient`.
- Instantiate `LLMClient` at startup with the Anthropic API key.

**Key differences**:

| Aspect | Old (gmail-to-trello) | New (agent-shared) |
|--------|----------------------|-------------------|
| Interface | Module-level `generate_card_name(subject, body, api_key)` | `LLMClient.call(prompt)` |
| Return type | `(name, source)` tuple, or `None` on failure | `LLMResponse` dataclass, or raises `LLMUnavailableError` |
| Failure handling | Returns `None`; caller uses subject line as fallback | Raises `LLMUnavailableError`; caller catches and applies fallback |
| Template syntax | `{{subject}}` double-brace with str.replace | `{subject}` single-brace with format_map |
| Prompt location | Inline string or file with double-brace syntax | File in `prompts/` dir with single-brace syntax |

**Update the agent's orchestrator**:
```python
# Old
from llm_client import generate_card_name
result = generate_card_name(subject, body, api_key)
if result is None:
    card_name = subject  # fallback
else:
    card_name, source = result

# New
from agent_shared.llm import LLMClient, LLMUnavailableError, PromptLoader
loader = PromptLoader(prompts_dir=str(Path(__file__).parent / "prompts"))
client = LLMClient(anthropic_api_key=api_key, ollama_model="qwen3:8b")

try:
    prompt = loader.load("card_name.md", {"subject": subject, "body": body})
    response = client.call(prompt, max_tokens=50)
    card_name = response.text.strip()
except LLMUnavailableError:
    card_name = subject  # fallback to subject line
```

**Update prompt templates**:
Old template (`prompts/card_name.md`):
```
Generate a task name for this email:
Subject: {{subject}}
Body: {{body}}
```

New template (`prompts/card_name.md`):
```
Generate a task name for this email:
Subject: {subject}
Body: {body}
```

**Mock target changes for tests**:
- Old: `patch("llm_client.anthropic.Anthropic")` or `patch("llm_client.requests.post")`
- New: `patch("agent_shared.llm.client.anthropic.Anthropic")` or
  `patch("agent_shared.llm.client.requests.post")`

**What to test**: Run all LLM-related tests. Verify fallback behavior (LLM failure → subject
line) is preserved. Verify that `LLMUnavailableError` is caught correctly.

**Rollback**: Revert the import and calling-code changes. Revert prompt template syntax.

---

### Phase 6: Migrate Prompt Templates

**What changes**:
- Rename `{{variable}}` to `{variable}` in all prompt template files.
- Verify `PromptLoader.load()` renders them correctly.

**Key differences**:
- Old: `str.replace("{{subject}}", subject)` — custom replacement, double braces
- New: `str.format_map(variables)` — Python built-in, single braces, KeyError on missing vars

**Common pitfalls**:
- A literal `{` or `}` in the template must be escaped as `{{` or `}}` in the new syntax.
  Example: a template containing `{"key": "value"}` (JSON example) must become
  `{{"key": "value"}}` to avoid being interpreted as a placeholder.
- All placeholders in the template must have corresponding entries in the `variables` dict.
  Unlike the old `str.replace` approach, `format_map` raises `KeyError` for undefined
  placeholders.

**What to test**: Run any tests that cover LLM prompt construction. Verify the rendered prompt
contains the correct substituted values.

**Rollback**: Revert template files to double-brace syntax and revert to the old PromptLoader.

---

### Phase 7: Remove Migrated Local Modules

**What changes**:
After all tests pass with the shared library, remove the local copies of:
- `config_loader.py`
- `logging_setup.py` (or equivalent)
- `db.py` (or equivalent)
- `trello_client.py`
- `llm_client.py`

Remove from `requirements.txt` any packages that are now provided transitively through
`agent-shared`'s `pyproject.toml` (e.g., `anthropic`, `requests`).

**What to test**: Full test suite. Verify no import errors. Verify no hidden dependency on the
deleted files.

**Rollback**: Restore deleted files from git history (`git checkout HEAD~1 -- path/to/file.py`).

---

## Common Pitfalls

### Mock target changes are the most common failure source
When the agent's tests mock `trello_client.requests.post` but the shared library uses
`requests.request`, the mock does not intercept the real call. Always verify mock targets after
migration. Use `pytest -s -v` to see which paths are being called.

### ConfigValidationError vs. ConfigError
Any test that does `pytest.raises(ConfigError)` will fail silently (no match) or loudly after
migration. Change to `pytest.raises(ConfigValidationError)` and update the import.

### Dict access vs. attribute access
Code like `config.trello_api_key` raises `AttributeError` when `config` is a dict. Change to
`config["trello_api_key"]`. A global search-replace for `.trello_` and `.anthropic_` attribute
accesses will catch most cases.

### Tuple unpacking of create_card return
`card_id, card_url = client.create_card(...)` will raise `ValueError: too many values to
unpack` because the return is a dict. Change to:
```python
result = client.create_card(...)
card_id, card_url = result["id"], result["url"]
```

### Template syntax mismatch
Running the new PromptLoader on old `{{variable}}` templates will return the template unchanged
(no substitution) rather than raising an error, because `{{` is the escape sequence for a
literal `{` in Python's format syntax. The result is a prompt containing `{{subject}}` which
the LLM will treat as literal text. Always re-run the LLM tests with real prompt content after
template migration.

---

## Rollback Plan

Each phase is independently rollbackable. If a phase breaks tests:

1. `git diff --stat` to see exactly which files changed.
2. `git stash` or `git checkout -- .` to discard the phase's changes.
3. Verify the test suite returns to green: `pytest tests/ -x`
4. Re-read the phase's "Key differences" section and the relevant `docs/` file.
5. Re-attempt with a corrected approach.

If multiple phases have been committed and the full rollback is needed:
```bash
git log --oneline -10   # find the last good commit hash
git reset --hard <hash>
```

The shared library itself does not hold any persistent state. Rolling back the consuming agent's
code is sufficient; no library changes are needed.
