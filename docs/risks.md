# Risks and Mitigations — agent-shared Library

## Risk Matrix Summary

| Risk | Likelihood | Impact | Mitigation Status |
|------|------------|--------|-------------------|
| Interface mismatch during migration | High | High | Implemented — create_card signature preserved |
| Config path resolution across agents | Medium | Medium | Implemented — 3-tier resolution with ENV_CONFIG_PATH |
| Trello API rate limits (429) | Low | Medium | Implemented — exponential backoff, 3 retries |
| Anthropic API unavailable | Low | Medium | Implemented — automatic Ollama fallback |
| Ollama unavailable | Medium | Medium | Implemented — LLMUnavailableError + health check |
| Prompt caching behavior | Medium | Low | Implemented — opt-in, cache_read_input_tokens check |
| JSON output parsing failure | Medium | Medium | Implemented — fence stripping, LLMJSONParseError |
| SQLite locking on Windows | Low | Low | Implemented — WAL mode, single-process per DB |
| Trello description character limit | Low | Medium | Documented — caller must truncate before calling |
| Logger handler accumulation | Medium | Low | Implemented — handlers cleared on name reuse |

---

## Risk Details

### 1. Interface Mismatch During Migration
**Likelihood**: High
**What would go wrong**: If `create_card`, `get_card`, or any other shared function has
different parameter names or return types than what the gmail-to-trello agent expects, the
migration would break the consuming agent's tests. Since the migration constraint prohibits
changing test assertions, any mismatch must be fixed in the library.

**Mitigations implemented**:
- `create_card(list_id, name, description, position, label_ids)` parameter names are preserved
  exactly from the gmail-to-trello agent's `trello_client.py`.
- `create_card` returns a raw dict (not `TrelloCard`) with `"id"` and `"url"` keys, matching
  the previous return type.
- `ConfigValidationError` replaces the old `ConfigError` — callers must catch the new name.
- `load_config` returns a plain dict rather than a typed dataclass tuple — callers must be
  updated to use dict key access instead of attribute access.
- The `anthropic_api_keys` dict structure (agent name → key) must be added to `.env.json`
  before migration begins.

**Residual risk**: Non-Trello function signatures (LLMClient, PromptLoader) are new and have
no backward-compat constraints. The calling agent's LLM integration code must be rewritten
regardless.

---

### 2. Config Path Resolution Across Agents
**Likelihood**: Medium
**What would go wrong**: Different agents run from different directories. The relative fallback
path `../config/.env.json` is resolved from `os.getcwd()`, which varies by agent. If the agent
is run from an unexpected directory (e.g., inside a virtualenv subdirectory), the fallback path
will resolve incorrectly and `FileNotFoundError` will be raised.

**Mitigations implemented**:
- Priority order: explicit `config_path` parameter > `ENV_CONFIG_PATH` env var > relative
  fallback. The first two are unambiguous; the fallback is last resort only.
- `ENV_CONFIG_PATH` is the recommended production setup for all agents. Each agent's startup
  script or `.env` file should set this.
- `config_path` parameter allows pinning the path in tests without environment variable pollution.
- `FileNotFoundError` is raised with the resolved path in the message, making the failure
  diagnosable.

**Residual risk**: If an agent is run via a task scheduler or a shell wrapper that changes cwd,
the fallback will break. Agents should always set ENV_CONFIG_PATH in production.

---

### 3. Trello API Rate Limits (429)
**Likelihood**: Low
**What would go wrong**: The Trello API allows 100 requests per 10-second window per token.
The grooming agent reading cards across many lists could approach this limit. A 429 response
without retry would cause the entire batch to fail.

**Mitigations implemented**:
- `_request()` in `TrelloClient` detects 429 and retries with exponential backoff: 1s, 2s, 4s
  waits between attempts.
- After 3 retries, `requests.HTTPError` is raised so the caller can log and handle the failure.
- `get_multiple_lists_cards` makes one API call per list (not per card), limiting total calls.
- All API calls are logged at DEBUG level, enabling post-hoc rate analysis.

**Residual risk**: The retry delay is blocking (time.sleep). For batch processing with many
lists, total wall-clock time could be significant if rate limits are hit repeatedly. An async
implementation would improve throughput in this scenario (out of scope for now).

---

### 4. Anthropic API Unavailable
**Likelihood**: Low
**What would go wrong**: The Anthropic API could be unreachable (network partition), rate-limited,
or reject the API key as invalid or expired. Without fallback, any LLM-dependent agent would
fail completely.

**Mitigations implemented**:
- Automatic fallback to Ollama on any exception from the Anthropic SDK.
- `LLMResponse.provider_used` records which provider actually served the request.
- If `anthropic_api_key` is None or empty, Anthropic is silently skipped — not an error condition.
- If both providers fail, `LLMUnavailableError` is raised with context about the last failure.

**Residual risk**: If the API key is valid but the account is suspended or rate-limited at the
account level (not per-request), Anthropic will fail on every call. In this case, Ollama carries
the full load until the account issue is resolved. The caller should monitor `provider_used` to
detect sustained Anthropic failures.

---

### 5. Ollama Unavailable
**Likelihood**: Medium
**What would go wrong**: The Ollama service may not be running (e.g., machine rebooted),
may have crashed, or the required model may not be loaded. If Anthropic also fails, the agent
has no LLM and cannot process items.

**Mitigations implemented**:
- `check_ollama_connectivity()` pings `GET /api/tags` and returns `True`/`False`. Never raises.
  Calling agents should call this at startup and log a warning if Ollama is unreachable.
- If Ollama fails after Anthropic also failed, `LLMUnavailableError` is raised with the last
  error included.
- Ollama's `stream=False` parameter is required to avoid streaming mode — omitting it causes
  silent JSON parse failures. This is implemented in `_call_ollama`.

**Residual risk**: A model loaded in Ollama that returns empty strings is not detected as a
failure — `_call_ollama` would return `LLMResponse(text="", ...)` without error. The calling
agent should validate that `response.text` is non-empty before using the result.

---

### 6. Prompt Caching Behavior
**Likelihood**: Medium
**What would go wrong**: Anthropic's prompt caching requires `cache_control={"type": "ephemeral"}`
on the system message. Cache hits are not guaranteed — they depend on Anthropic's infrastructure
load and the stability of the cached content. A caller expecting cache savings might see zero
hits if content changes slightly between calls.

**Mitigations implemented**:
- `cache_system_prompt=True` is opt-in. The caller decides when caching is appropriate (same
  system prompt across many calls in a batch).
- Cache hit confirmation uses `response.usage.cache_read_input_tokens > 0`, which is the
  authoritative Anthropic field (not a guess). Field is `cache_read_input_tokens`, not
  `cache_hit` (see LESSONS.md).
- `LLMResponse.cached` lets the caller monitor cache effectiveness.
- The `betas=["prompt-caching-2024-07-31"]` beta header is NOT used in the current
  implementation; cache_control is set directly on the content block per current Anthropic SDK
  conventions.

**Residual risk**: Anthropic may change the caching API or content block format in a future SDK
version. Pin the `anthropic` SDK version in `pyproject.toml` to avoid unexpected breakage.

---

### 7. JSON Output Parsing Failure
**Likelihood**: Medium
**What would go wrong**: When `json_output=True`, the LLM may return prose explaining why it
cannot generate JSON, or return JSON wrapped in markdown code fences, or return JSON with
trailing commas. `json.loads()` would fail, and the calling agent would receive an exception
rather than a parsed object.

**Mitigations implemented**:
- Markdown code fences (` ```json ` and ` ``` `) are stripped via regex before parsing.
- `LLMJSONParseError` includes the `raw_text` attribute containing the original response,
  enabling the caller to log and diagnose the exact output that failed.
- JSON parse errors are NOT retried with the other provider (by design). A malformed prompt
  will likely produce malformed output on any LLM; fixing the prompt is the correct response.
- The caller is responsible for validating the JSON schema. This library only guarantees
  syntactic validity.

**Residual risk**: LLMs sometimes produce trailing commas or JavaScript-style comments in "JSON"
that `json.loads()` rejects. If this is a recurring issue with a specific prompt, the caller
can post-process `raw_text` with a lenient parser (e.g., `demjson3`) before raising.

---

### 8. SQLite Locking on Windows
**Likelihood**: Low
**What would go wrong**: SQLite in WAL mode can encounter locking conflicts if multiple
processes write to the same database file simultaneously. On Windows, file locking behavior
differs from POSIX systems, making this more likely to cause `OperationalError: database is
locked`.

**Mitigations implemented**:
- Each agent uses its own database file path. The shared library's `db.py` does not reference
  any specific path — the caller provides it.
- `db_connection` context manager ensures connections are always closed (via `finally`), even
  on exceptions.
- WAL mode is enabled by default for better concurrent read performance.
- Each agent is expected to be a single process accessing its own database.

**Residual risk**: If an agent is run as multiple parallel processes (e.g., separate scheduled
runs that overlap), locking conflicts can occur. The recommended mitigation is to add a
check-and-skip mechanism in the agent's startup to detect if another instance is already running
(e.g., a PID file or lock file).

---

### 9. Trello Card Description Character Limit
**Likelihood**: Low
**What would go wrong**: Trello enforces a 16,384-character limit on card descriptions. The API
returns HTTP 400 if the limit is exceeded. An agent that appends email body content to card
descriptions without truncation will fail silently or visibly depending on error handling.

**Mitigations implemented**:
- Documented in LESSONS.md.
- `create_card` and `update_card` accept the `description` parameter without length validation —
  this is intentional. The calling agent owns business logic about how to truncate and must
  enforce the limit before calling.

**Recommended mitigation for consuming agents**: Check `len(description) > 16000` before
calling. Truncate and append a notice: `"\n\n[Truncated: description exceeded 16,000 characters]"`.

---

### 10. Logger Handler Accumulation
**Likelihood**: Medium
**What would go wrong**: Python's `logging.getLogger(name)` returns the same instance for the
same name across the entire process. If `setup_logging` is called multiple times with the same
logger name (e.g., in tests or after agent restart), handlers accumulate, causing duplicate log
output.

**Mitigations implemented**:
- `setup_logging` explicitly clears existing handlers before adding the new `RotatingFileHandler`.
- LESSONS.md documents this behavior prominently.
- All tests use unique logger names per test function to prevent cross-test state contamination.

**Residual risk**: If a calling agent's code adds a `StreamHandler` manually after calling
`setup_logging`, a subsequent call to `setup_logging` will remove it. The docstring warns callers
not to rely on handlers added externally if they plan to re-call `setup_logging`.
