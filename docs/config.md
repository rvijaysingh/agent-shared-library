# Configuration Reference — agent-shared Library

## What This Library Configures

`agent-shared` reads exactly one configuration source: a global `.env.json` file read by
`agent_shared.infra.config_loader.load_config()`. Every other value is passed as a function
or constructor parameter by the calling agent.

The library does **not** configure:
- Agent-specific business rules (list IDs, label names, email filters) — these belong to each
  agent's own config file.
- Its own prompt files — the calling agent owns its `prompts/` directory.
- Log file locations or logger names — the calling agent decides.
- Database file paths — the calling agent decides.

---

## Global .env.json Schema

| Field | Type | Used By | Required | Default |
|-------|------|---------|----------|---------|
| `trello_api_key` | string | `TrelloClient` constructor | Yes, if using Trello | None |
| `trello_api_token` | string | `TrelloClient` constructor | Yes, if using Trello | None |
| `trello_board_id` | string | `TrelloClient` constructor | Yes, if using Trello | None |
| `ollama_host` | string | `LLMClient` constructor | No | `"http://localhost:11434"` |
| `ollama_model` | string | `LLMClient` constructor | No | `"qwen3:8b"` |
| `anthropic_api_keys` | dict (str→str) | `LLMClient` constructor | No (falls back to Ollama) | None |

### Field Details

**`trello_api_key`** — Your Trello application API key. Obtained from
https://trello.com/app-key. Scoped to your Trello account; all agents share the same key.

**`trello_api_token`** — Your Trello OAuth token. Generated from the API key page. Has
read/write access to boards accessible to your account. Treat as a secret — do not commit
to source control.

**`trello_board_id`** — The default board ID. Found in the board URL:
`https://trello.com/b/{board_id}/board-name`. The agent uses this as the default for
board-scoped operations (get_board_labels, get_board_lists, create_label, validate_list_exists).
Individual card operations use card IDs which are globally unique and do not need a board ID.

**`ollama_host`** — Base URL of the local Ollama service. Must not have a trailing slash.
The library appends paths like `/api/generate` and `/api/tags`. If Ollama is on a remote
machine, use its full URL (e.g., `"http://192.168.1.100:11434"`).

**`ollama_model`** — The Ollama model name as it appears in `ollama list`. Must be pulled
before use: `ollama pull qwen3:8b`. If this model is not available, Ollama calls will fail.

**`anthropic_api_keys`** — A dictionary mapping agent name strings to Anthropic API key
strings. Each consuming agent selects its own key by name. This design allows per-agent
key rotation and cost tracking via Anthropic's usage dashboard.

Example:
```json
{
  "anthropic_api_keys": {
    "gmail-to-trello": "sk-ant-api03-...",
    "grooming": "sk-ant-api03-...",
    "duplicate-detector": "sk-ant-api03-..."
  }
}
```

The calling agent retrieves its key as:
```python
config = load_config(required_fields=["anthropic_api_keys"])
api_key = config["anthropic_api_keys"]["gmail-to-trello"]
client = LLMClient(anthropic_api_key=api_key)
```

If `anthropic_api_keys` is absent from the config (or the agent name is not in the dict),
the calling agent can pass `anthropic_api_key=None` to `LLMClient`, which will skip Anthropic
and use Ollama directly. This is not an error condition.

---

## Config Path Resolution Order

`load_config()` resolves the config file path using this priority order:

1. **`config_path` parameter** (highest priority): explicit absolute or relative path.
   ```python
   load_config(config_path="/home/devon/config/.env.json")
   ```

2. **`ENV_CONFIG_PATH` environment variable**: if set, the path it contains is used.
   ```python
   # Shell:
   # set ENV_CONFIG_PATH=C:\config\.env.json   (Windows cmd)
   # $env:ENV_CONFIG_PATH = "C:\config\.env.json"  (PowerShell)
   load_config()  # reads from ENV_CONFIG_PATH
   ```

3. **Fallback relative path** (lowest priority): `../config/.env.json` relative to
   `os.getcwd()`. This works when the agent is run from its repository root, where `cwd` is
   the agent directory and the config lives one level up in a shared `config/` directory.

If none of these paths resolves to an existing file, `FileNotFoundError` is raised with the
resolved path included in the message.

### Path Resolution Examples

Given directory structure:
```
C:\Users\devon\
├── config\
│   └── .env.json              ← global config
├── gmail-to-trello\           ← agent repo root
│   └── agent.py
└── agent-shared-library\      ← this library
```

**Production (ENV_CONFIG_PATH, recommended)**:
```batch
:: Windows cmd
set ENV_CONFIG_PATH=C:\Users\devon\config\.env.json
python agent.py
```
```powershell
# PowerShell
$env:ENV_CONFIG_PATH = "C:\Users\devon\config\.env.json"
python agent.py
```

**Production (fallback, requires correct cwd)**:
```batch
cd C:\Users\devon\gmail-to-trello
python agent.py
:: load_config() resolves ../config/.env.json = C:\Users\devon\config\.env.json ✓
```

**Tests (explicit path, always correct)**:
```python
load_config(config_path=str(tmp_path / ".env.json"))
```

---

## Setting ENV_CONFIG_PATH on Windows

### Windows Command Prompt (temporary, for current session)
```batch
set ENV_CONFIG_PATH=C:\Users\devon\config\.env.json
```

### Windows Command Prompt (permanent, for user)
```batch
setx ENV_CONFIG_PATH "C:\Users\devon\config\.env.json"
```
Note: `setx` takes effect in new command prompt windows only.

### PowerShell (temporary)
```powershell
$env:ENV_CONFIG_PATH = "C:\Users\devon\config\.env.json"
```

### PowerShell (permanent, for current user)
```powershell
[System.Environment]::SetEnvironmentVariable(
    "ENV_CONFIG_PATH",
    "C:\Users\devon\config\.env.json",
    "User"
)
```

### Windows Task Scheduler
When using Task Scheduler to run agents, add the environment variable in the task's
"Edit Action" → "Add arguments" or set it in the task's environment block. The scheduler's
working directory may differ from the agent's repo root, making ENV_CONFIG_PATH essential.

---

## Example .env.json (Sanitized)

```json
{
  "trello_api_key": "your-32-char-trello-api-key-here",
  "trello_api_token": "your-64-char-trello-oauth-token-here",
  "trello_board_id": "oNIV6Mcq",
  "ollama_host": "http://localhost:11434",
  "ollama_model": "qwen3:8b",
  "anthropic_api_keys": {
    "gmail-to-trello": "sk-ant-api03-your-key-here",
    "grooming": "sk-ant-api03-your-other-key-here"
  }
}
```

Store this file at:
- `C:\Users\devon\config\.env.json` (recommended, parent of all agent repos)
- Or any path referenced by `ENV_CONFIG_PATH`

**Never commit this file to source control.** Verify it is in the parent `.gitignore`.

A `.env.json.example` file should be committed to the config directory with placeholder values
to document the required structure for new machines.

---

## Validating Required Fields at Agent Startup

Each consuming agent specifies exactly which fields it needs. The library validates them at
`load_config` call time, failing fast with a clear error naming the missing field.

**gmail-to-trello agent** example:
```python
config = load_config(
    required_fields=[
        "trello_api_key",
        "trello_api_token",
        "trello_board_id",
        "anthropic_api_keys",
    ]
)
```

**grooming agent** example:
```python
config = load_config(
    required_fields=[
        "trello_api_key",
        "trello_api_token",
        "trello_board_id",
        "anthropic_api_keys",
        "ollama_host",
        "ollama_model",
    ]
)
```

A missing required field raises `ConfigValidationError` immediately at startup, before any API
calls are made. The error message includes the field name and the config file path.

---

## Per-Agent API Key Design

`anthropic_api_keys` is a dict rather than a single string to support:

1. **Cost tracking**: Each agent can use a different Anthropic API key, and usage can be tracked
   separately in Anthropic's dashboard by filtering by key.

2. **Key rotation**: If one agent's key is compromised, only that key needs rotation. Other
   agents are unaffected.

3. **Rate limit isolation**: Different keys have independent rate limits (if using multiple
   accounts). Preventing one high-volume agent from starving lower-volume agents.

The calling agent is responsible for selecting the correct key:
```python
keys = config.get("anthropic_api_keys", {})
api_key = keys.get("my-agent-name")  # None if not configured → falls back to Ollama
client = LLMClient(anthropic_api_key=api_key)
```

Using `.get()` (returning None) rather than `["key"]` (raising KeyError) means the agent
gracefully falls back to Ollama if its key is not yet configured — appropriate during initial
setup.
