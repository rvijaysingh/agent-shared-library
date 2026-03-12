# Architecture — agent-shared Library

## Purpose and Design Philosophy

`agent-shared` is a reusable Python library for a personal AI agent ecosystem. It wraps three
external APIs (Trello, Anthropic, Ollama) and provides SQLite and logging infrastructure. It is
a library, not an application: it has no entry point, no main(), no orchestrator, and no config
files of its own.

Core constraints that govern every design decision:

- **Config via parameters**: Every function and constructor receives configuration as explicit
  arguments. No module-level globals, no singletons, no os.environ reads except in
  `config_loader` (whose sole job is to read the global .env.json).
- **Synchronous only**: All functions are blocking. No async, no threads, no event loops.
- **Fail loudly**: Errors raise exceptions with context. No swallowed exceptions, no silent empty
  returns.
- **Dependency-free where possible**: Standard library used for JSON, logging, SQLite. Only
  `requests`, `anthropic`, and `pytest` are external dependencies for runtime and testing.
- **Library, not framework**: No base classes, plugin systems, or registries. Each submodule does
  one thing and can be used independently.

---

## Submodule Dependency Graph

```
agent_shared (package root)
├── models.py                   ← LLMResponse, ProcessingResult
│                                 (no internal imports)
│
├── infra/
│   ├── config_loader.py        ← reads .env.json → dict
│   │                             (stdlib only: json, os, pathlib)
│   ├── logging_setup.py        ← returns Logger with RotatingFileHandler
│   │                             (stdlib only: logging, os)
│   └── db.py                   ← SQLite connection factory + context manager
│                                 (stdlib only: sqlite3, os, contextlib)
│
├── trello/
│   ├── models.py               ← TrelloCard, TrelloList, TrelloLabel dataclasses
│   │                             (stdlib only: dataclasses)
│   └── client.py               ← TrelloClient REST API wrapper
│                                 imports: requests, agent_shared.trello.models
│
└── llm/
    ├── client.py               ← LLMClient with Anthropic/Ollama fallback
    │                             imports: anthropic, requests, agent_shared.models
    └── prompt_loader.py        ← PromptLoader for markdown templates
                                  (stdlib only: pathlib, logging)
```

External dependency arrows:

```
config_loader  ──────────────►  .env.json (filesystem)
trello/client  ──────────────►  Trello REST API (HTTPS)
llm/client     ──────────────►  Anthropic API (HTTPS)
               ──────────────►  Ollama /api/generate (HTTP localhost)
db             ──────────────►  SQLite file (filesystem)
```

There are no circular imports. `models.py` is the only shared dependency imported by both
`llm/client.py` and potentially the calling agent.

---

## Data Flow Patterns

### Pattern A: Config Load → TrelloClient → Card Operations

```
Calling agent
    │
    ├─ load_config(required_fields=[...], config_path="...")
    │       │
    │       ├─ Reads .env.json from disk
    │       ├─ Validates required fields
    │       └─ Returns: plain dict
    │
    ├─ TrelloClient(api_key=cfg["trello_api_key"],
    │               api_token=cfg["trello_api_token"],
    │               board_id=cfg["trello_board_id"])
    │       └─ Stores credentials in instance (no I/O at construction)
    │
    ├─ client.create_card(list_id, name, description)
    │       │
    │       ├─ Builds request body: {idList, name, desc, pos}
    │       ├─ Calls _request("POST", url, json=body)
    │       │       ├─ Merges auth params (key, token)
    │       │       ├─ calls requests.request(method, url, params=..., json=..., timeout=15)
    │       │       ├─ On 429: exponential backoff (1s, 2s, 4s), max 3 retries
    │       │       └─ On success: returns requests.Response
    │       └─ Returns: response.json() → dict with "id", "url", etc.
    │
    └─ result["id"], result["url"]  ← used by agent for record-keeping
```

### Pattern B: PromptLoader → LLMClient → LLMResponse

```
Calling agent
    │
    ├─ PromptLoader(prompts_dir="/path/to/agent/prompts")
    │       └─ Stores prompts_dir as Path (no I/O at construction)
    │
    ├─ loader.load("card_name.md", {"subject": "...", "body": "..."})
    │       ├─ Reads template file from disk
    │       ├─ Calls content.format_map(variables)
    │       └─ Returns: rendered string prompt
    │
    ├─ LLMClient(anthropic_api_key=cfg["anthropic_api_keys"]["agent-name"],
    │            ollama_host=cfg.get("ollama_host", "http://localhost:11434"),
    │            ollama_model=cfg.get("ollama_model", "qwen3:8b"))
    │       └─ Stores config in instance (no I/O at construction)
    │
    ├─ client.call(prompt, system_prompt=..., json_output=True, cache_system_prompt=True)
    │       │
    │       ├─ Appends JSON instruction to prompt (if json_output=True)
    │       ├─ Tier 1: Anthropic
    │       │       ├─ Builds messages payload
    │       │       ├─ Adds cache_control block to system (if cache_system_prompt=True)
    │       │       ├─ anthropic.Anthropic(api_key=...).messages.create(...)
    │       │       ├─ Reads response.usage.cache_read_input_tokens for cache hit
    │       │       └─ Returns: LLMResponse(provider_used="anthropic", ...)
    │       │
    │       ├─ On Anthropic failure: log warning, fall through to Tier 2
    │       │
    │       ├─ Tier 2: Ollama
    │       │       ├─ POST {model, prompt, stream: false} to /api/generate
    │       │       └─ Returns: LLMResponse(provider_used="ollama", ...)
    │       │
    │       ├─ If json_output=True: strip fences, validate json.loads(), return cleaned text
    │       └─ If both fail: raise LLMUnavailableError
    │
    └─ response.text  ← JSON string or plain text, ready for agent use
```

### Pattern C: db_connection → ensure_table → Read/Write

```
Calling agent
    │
    ├─ with db_connection(db_path) as conn:
    │       │
    │       ├─ get_db_connection(db_path)
    │       │       ├─ os.makedirs(..., exist_ok=True)
    │       │       ├─ sqlite3.connect(db_path)
    │       │       ├─ conn.execute("PRAGMA journal_mode=WAL")
    │       │       ├─ conn.execute("PRAGMA foreign_keys=ON")
    │       │       └─ conn.row_factory = sqlite3.Row
    │       │
    │       ├─ ensure_table(conn, "CREATE TABLE IF NOT EXISTS processed (...)")
    │       │       ├─ conn.execute(create_sql)
    │       │       └─ conn.commit()
    │       │
    │       ├─ conn.execute("INSERT INTO processed (...) VALUES (?)", (value,))
    │       ├─ conn.execute("SELECT * FROM processed WHERE ...")
    │       │       └─ Returns: sqlite3.Row — access columns by name: row["column"]
    │       │
    │       └─ On clean exit: conn.commit()
    │          On exception: conn.rollback(), re-raise
    │          Always: conn.close()
    │
    └─ Agent inspects rows or handles ProcessingResult
```

---

## Module Responsibilities

### `infra/config_loader.py`
Single responsibility: read one JSON file from disk, validate required keys, return a plain dict.
The resolution priority (explicit param > ENV_CONFIG_PATH > fallback relative path) isolates all
path-resolution logic here. All other modules are path-agnostic.

### `infra/logging_setup.py`
Creates a named `logging.Logger` with a `RotatingFileHandler`. Clears existing handlers on the
same logger name to prevent accumulation across repeated calls (see LESSONS.md). The caller owns
the log path, logger name, and rotation policy.

### `infra/db.py`
SQLite connection factory with WAL mode, foreign key enforcement, and `sqlite3.Row` factory.
The `db_connection` context manager provides ACID transactional boundaries. The caller provides
the database path and all SQL — this module generates no SQL and enforces no schema.

### `trello/models.py`
Plain dataclasses: `TrelloCard`, `TrelloList`, `TrelloLabel`. No business logic, no API calls.
`TrelloCard.labels` uses `field(default_factory=list)` to prevent shared mutable defaults.

### `trello/client.py`
All Trello REST operations as methods on `TrelloClient`. Auth params (key, token) merged on
every request via `_request()`. Rate-limit retry (429 → 1s/2s/4s backoff, max 3 retries).
The `_parse_card()` module-level helper normalizes raw API dicts into `TrelloCard` dataclasses.
The `create_card` signature is preserved from the gmail-to-trello agent for migration
compatibility: parameter names `list_id`, `name`, `description` map to Trello API fields
`idList`, `name`, `desc`.

### `llm/client.py`
`LLMClient` implements a two-tier fallback chain: Anthropic first (if api_key is set), Ollama
second. `LLMJSONParseError` is not a provider failure — it propagates immediately without
triggering fallback. `LLMUnavailableError` is raised only when both tiers fail. Token fields are
`input_tokens`/`output_tokens` (Anthropic naming, not OpenAI's `prompt_tokens`). Prompt caching
uses `cache_control={"type": "ephemeral"}` on the system block; cache hit is confirmed via
`response.usage.cache_read_input_tokens > 0`.

### `llm/prompt_loader.py`
Loads markdown files from a caller-supplied directory and substitutes `{placeholder}` variables
using `str.format_map()`. Re-reads the file on every call (no caching). Raises `KeyError` for
missing placeholders (not a silent no-op). The library ships no prompt files.

### `models.py` (top-level)
`LLMResponse` and `ProcessingResult` dataclasses. `ProcessingResult` auto-populates `timestamp`
with UTC ISO 8601 if left empty. `LLMResponse` is also re-exported from `agent_shared.llm` for
convenience.

---

## Key Design Decisions

### Decision 1: No Module-Level Globals or Singletons
**Context**: Several library patterns (service locators, global clients) would allow callers to
avoid passing config repeatedly.
**Options Considered**: (a) Global `TrelloClient` instance configured once; (b) config dict
cached at import time; (c) all config passed as parameters.
**Chosen Approach**: All config via parameters.
**Tradeoffs**: Optimizes for testability (each test can pass its own fake credentials without
monkeypatching globals), and for multi-agent safety (two agents can use different Trello boards
in the same process). Sacrifices convenience for single-agent scripts. Would revisit if the same
library were used in a web server context where request-scoped config is needed.

### Decision 2: Anthropic → Ollama Fallback, Not Configurable Order
**Context**: Two LLM providers with different reliability profiles.
**Options Considered**: (a) Configurable fallback order; (b) Anthropic-only; (c) Ollama-only;
(d) Fixed Anthropic-first.
**Chosen Approach**: Anthropic first, Ollama second, fixed order.
**Tradeoffs**: Optimizes for inference quality (Anthropic Haiku > Ollama qwen3:8b) and low
latency (Anthropic's API is fast). Sacrifices flexibility for agents that prefer local inference.
Would revisit if cost constraints require Ollama-first operation.

### Decision 3: LLMJSONParseError Does Not Trigger Fallback
**Context**: When `json_output=True`, a malformed response could be retried with the other
provider.
**Options Considered**: (a) Retry with Ollama on JSON parse failure; (b) Raise immediately.
**Chosen Approach**: Raise `LLMJSONParseError` immediately, do not fall back.
**Tradeoffs**: Optimizes for correctness and debuggability — if the same prompt produces
malformed JSON on Anthropic, it will likely do the same on Ollama. The calling agent sees the
error and the raw text, enabling targeted prompt fixes. Sacrifices the marginal chance that
Ollama would return valid JSON when Anthropic returned prose.

### Decision 4: create_card Returns Raw API Dict, Not TrelloCard
**Context**: Migration compatibility with gmail-to-trello agent.
**Options Considered**: (a) Return `TrelloCard` dataclass; (b) Return raw dict.
**Chosen Approach**: Return raw dict (same as gmail-to-trello agent's interface).
**Tradeoffs**: Optimizes for zero-change migration — the calling agent accesses `result["id"]`
and `result["url"]` without modification. Sacrifices type safety for the creation path.
Read operations (`get_card`, `get_list_cards`) return `TrelloCard` for structured access.

### Decision 5: PromptLoader Uses Python format_map, Not Jinja2
**Context**: Templates need variable substitution.
**Options Considered**: (a) Jinja2 (logic, loops, conditionals); (b) Python str.format_map
(simple substitution); (c) str.replace with {{double-brace}} syntax.
**Chosen Approach**: Python `str.format_map()` with single-brace `{placeholder}` syntax.
**Tradeoffs**: Optimizes for zero external dependencies and simplicity. Sacrifices template
logic (loops, conditionals). Would revisit if templates need conditional sections. Note: the
gmail-to-trello agent used `{{double-brace}}` with str.replace — migration requires template
re-formatting to single-brace syntax.
