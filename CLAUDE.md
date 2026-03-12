# Agent Shared Library (agent-shared)

## Required Reading
Always read LESSONS.md before making any changes to understand
known issues and working patterns inherited from the gmail-to-trello
agent and discovered during this library's development.

## Purpose
A reusable Python library providing Trello API operations, LLM
inference (Anthropic primary, Ollama fallback), prompt template
loading, config loading, logging setup, and SQLite scaffolding
for a personal AI agent ecosystem. This is a library, not an
application. It has no entry point, no main(), no orchestrator,
and no configuration files of its own. Every function accepts
configuration as parameters from the calling agent.

## Development Loop
- Test command: `pytest tests/ -x`
- After any code change, run the test command and fix all failures
  before considering the task complete. Do not ask the user to run
  code or paste errors.
- If tests fail, read the traceback, identify the root cause, fix
  it, and re-run. Repeat until 0 failures. Do not stop after a
  single fix attempt if failures remain.
- If a fix attempt does not reduce the failure count after two
  iterations, re-read LESSONS.md and the relevant architecture doc
  before trying a different approach.
- If progress stalls (same error after 3 attempts), pivot to the
  documented fallback approach in the relevant architecture section
  rather than iterating further on the same strategy.
- This library wraps three external APIs (Trello, Anthropic, Ollama).
  All tests must use mocked API responses, never live calls. Fixture
  data lives in tests/fixtures/.

## Architecture Constraints
- Runtime: Windows 10/11, Python 3.13
- This is a library installed via `pip install -e ../agent-shared`
  into each consuming agent's virtualenv.
- All functions accept configuration as parameters. No config files,
  no environment variable reads (except config_loader, whose job is
  to read the global .env.json), no module-level globals, no
  singletons.
- config_loader is the sole exception: it reads the global .env.json
  and returns a plain dict. It does NOT set globals or cache state.
- LLM primary: Anthropic API (Claude Haiku 4.5). API key selected
  per-agent from the `anthropic_api_keys` dict in global config.
- LLM fallback: Ollama running locally (host and model name passed
  as parameters, defaults: http://localhost:11434, qwen3:8b).
- Trello: REST API with key + token auth. All credentials passed
  as parameters.
- No browser automation. All interactions are API-based.
- No async. All functions are synchronous.

## Documentation Structure

- docs/architecture.md -- Library design: submodule responsibilities,
  dependency graph between submodules, data flow for common usage
  patterns (card creation, LLM call with fallback, config loading).
  Read this first for system understanding.
- docs/risks.md -- Identified risks with likelihood, impact, and
  concrete mitigations. Review when adding new submodules or
  debugging consumer agent failures.
- docs/testing.md -- Test case table, fixture inventory, testing
  strategy, mocking patterns for each external API. Read before
  writing or updating tests.
- docs/config.md -- Global .env.json schema, required fields per
  submodule, example values, resolution logic. Reference for
  machine setup or new agents.
- docs/migration.md -- Step-by-step instructions for refactoring
  the gmail-to-trello agent to use this library, with rollback plan.
  Reference for migrating future agents.
- LESSONS.md -- Operational findings: API quirks, Trello description
  rendering issues, LLM prompt caching behavior, config loading
  edge cases. Seeded with relevant lessons from the gmail-to-trello
  agent.

All submodules should be built defensively against the risks
identified in docs/risks.md. Run pytest before every commit. Test
coverage requirements are defined in docs/testing.md.

## Project Structure
agent-shared/
  CLAUDE.md
  README.md
  LESSONS.md
  pyproject.toml
  .gitignore
  src/
    agent_shared/
      __init__.py                  # Package root, version string
      models.py                    # ProcessingResult, LLMResponse dataclasses
      trello/
        __init__.py                # Re-exports: TrelloClient, TrelloCard,
                                   #   TrelloList, TrelloLabel
        client.py                  # Trello REST API client (all operations)
        models.py                  # TrelloCard, TrelloList, TrelloLabel
      llm/
        __init__.py                # Re-exports: LLMClient, PromptLoader,
                                   #   LLMResponse
        client.py                  # LLM wrapper: Anthropic (primary),
                                   #   Ollama (fallback), structured JSON
                                   #   output, prompt caching
        prompt_loader.py           # Load markdown templates with variable
                                   #   substitution from caller-specified path
      infra/
        __init__.py                # Re-exports: load_config,
                                   #   setup_logging, get_db_connection
        config_loader.py           # Reads global .env.json, validates
                                   #   required fields, returns dict
        logging_setup.py           # Rotating file handler factory
        db.py                      # SQLite connection factory, table-exists
                                   #   check, ensure-table, context manager
  tests/
    __init__.py
    test_config_loader.py
    test_logging_setup.py
    test_db.py
    test_trello_client.py
    test_trello_models.py
    test_llm_client.py
    test_prompt_loader.py
    test_models.py
    test_integration.py            # Simulated consumer usage patterns
    fixtures/
      sample_env.json              # Valid global config for tests
      trello_responses/            # Mock Trello API JSON responses
      llm_responses/               # Mock Anthropic and Ollama responses
  docs/
    architecture.md
    risks.md
    testing.md
    config.md
    migration.md

## Configuration Design
This library reads one config source and accepts all other
configuration as function/constructor parameters.

1. Global .env.json (read by config_loader only):
   Path resolved from ENV_CONFIG_PATH environment variable, falling
   back to ../config/.env.json relative to the consuming agent's
   repo root. The consuming agent calls load_config() and passes
   the returned dict (or individual values from it) to library
   functions.

   Fields this library's submodules expect to receive (via params):
   - trello_api_key (trello submodule)
   - trello_api_token (trello submodule)
   - trello_board_id (trello submodule, default: oNIV6Mcq)
   - ollama_host (llm submodule, default: http://localhost:11434)
   - ollama_model (llm submodule, default: qwen3:8b)
   - anthropic_api_keys (llm submodule): dict keyed by agent name,
     e.g. {"gmail-to-trello": "sk-ant-...", "grooming": "sk-ant-..."}

   config_loader.load_config() accepts a list of required_fields.
   It raises ConfigValidationError if any required field is missing
   or empty. Each consuming agent specifies exactly which fields
   it needs; the library does not enforce a universal required set.

2. No agent-specific config files. This library never reads
   agent_config.json or any other agent-specific config. The
   consuming agent loads its own config and passes values in.

3. No prompt files shipped with this library. The consuming agent
   owns its prompts/ directory and passes file paths to
   PromptLoader.

## Submodule Specifications

### infra/config_loader.py

```python
class ConfigValidationError(Exception):
    """Raised when required config fields are missing or empty."""
    pass

def load_config(
    required_fields: list[str] | None = None,
    config_path: str | None = None
) -> dict:
    """
    Load global .env.json and validate required fields.

    Resolution order for config path:
    1. config_path parameter (if provided)
    2. ENV_CONFIG_PATH environment variable
    3. ../config/.env.json relative to caller's working directory

    Returns: plain dict of all config key-value pairs.
    Raises: ConfigValidationError if required fields missing/empty.
    Raises: FileNotFoundError if config file not found at any path.
    Raises: json.JSONDecodeError if config file is invalid JSON.
    """
```

### infra/logging_setup.py

```python
def setup_logging(
    log_path: str,
    logger_name: str,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    log_level: int = logging.INFO
) -> logging.Logger:
    """
    Create and return a named logger with a rotating file handler.

    The caller owns the log path and logger name. This function
    creates parent directories if they don't exist.

    Returns: configured Logger instance.
    """
```

### infra/db.py

```python
def get_db_connection(db_path: str) -> sqlite3.Connection:
    """
    Create a SQLite connection with WAL mode and foreign keys enabled.
    Creates parent directories and the DB file if they don't exist.
    Returns: sqlite3.Connection with row_factory = sqlite3.Row.
    """

def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""

def ensure_table(conn: sqlite3.Connection, create_sql: str) -> None:
    """
    Execute a CREATE TABLE IF NOT EXISTS statement.
    The caller provides the full SQL, including the table name
    and schema. This function does not generate SQL.
    """

@contextmanager
def db_connection(db_path: str):
    """
    Context manager that yields a connection and commits on
    success, rolls back on exception, and always closes.
    """
```

### trello/models.py

```python
@dataclass
class TrelloLabel:
    id: str
    name: str
    color: str | None = None

@dataclass
class TrelloCard:
    id: str
    name: str
    description: str = ""
    list_id: str = ""
    position: float = 0.0
    labels: list[TrelloLabel] = field(default_factory=list)
    due_date: str | None = None
    url: str = ""
    last_activity: str = ""
    closed: bool = False

@dataclass
class TrelloList:
    id: str
    name: str
    closed: bool = False
    position: float = 0.0
```

### trello/client.py

```python
class TrelloClient:
    def __init__(self, api_key: str, api_token: str, board_id: str):
        """All credentials passed explicitly. No config file reads."""

    # --- Card creation (preserved from gmail-to-trello) ---
    def create_card(
        self,
        list_id: str,
        name: str,
        description: str = "",
        position: str = "top",
        label_ids: list[str] | None = None
    ) -> dict:
        """
        Create a card on the specified list.
        Returns: raw Trello API response dict with 'id', 'url', etc.
        Interface preserved exactly from gmail-to-trello agent's
        trello_client.py for migration compatibility.
        """

    # --- Card reads (new for grooming agent) ---
    def get_card(self, card_id: str) -> TrelloCard:
        """Get a single card by ID with all fields."""

    def get_list_cards(
        self,
        list_id: str,
        include_closed: bool = False
    ) -> list[TrelloCard]:
        """Get all cards on a list, parsed into TrelloCard objects."""

    def get_multiple_lists_cards(
        self,
        list_ids: list[str],
        include_closed: bool = False
    ) -> dict[str, list[TrelloCard]]:
        """
        Get cards across multiple lists.
        Returns: dict mapping list_id to list of TrelloCard objects.
        """

    # --- Card mutations (new for grooming agent) ---
    def move_card(
        self,
        card_id: str,
        target_list_id: str,
        position: str | float = "top"
    ) -> dict:
        """Move a card to a different list and/or position."""

    def update_card(
        self,
        card_id: str,
        name: str | None = None,
        description: str | None = None,
        position: str | float | None = None,
        label_ids: list[str] | None = None,
        due_date: str | None = None,
        closed: bool | None = None
    ) -> dict:
        """
        Update one or more card fields. Only non-None params are sent.
        Returns: raw Trello API response dict.
        """

    def add_comment(self, card_id: str, text: str) -> dict:
        """Add a comment to a card. Returns API response."""

    def get_card_actions(
        self,
        card_id: str,
        action_filter: str = "all",
        limit: int = 50
    ) -> list[dict]:
        """Get card activity/action history."""

    # --- Label operations (new for grooming agent) ---
    def get_board_labels(self) -> list[TrelloLabel]:
        """Get all labels on the board."""

    def create_label(
        self,
        name: str,
        color: str = "null"
    ) -> TrelloLabel:
        """Create a label on the board."""

    # --- List operations ---
    def get_board_lists(
        self,
        include_closed: bool = False
    ) -> list[TrelloList]:
        """Get all lists on the board."""

    def validate_list_exists(self, list_id: str) -> bool:
        """Check if a list ID exists on the board. Used at startup."""
```

### llm/client.py

```python
@dataclass
class LLMResponse:
    text: str
    provider_used: str          # "anthropic" or "ollama"
    tokens_in: int = 0
    tokens_out: int = 0
    cached: bool = False        # True if Anthropic cache hit
    model: str = ""

class LLMClient:
    def __init__(
        self,
        anthropic_api_key: str | None = None,
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "qwen3:8b",
        anthropic_model: str = "claude-haiku-4-5-20241022"
    ):
        """
        All config passed explicitly. If anthropic_api_key is None
        or empty, Anthropic is skipped and Ollama is tried first.
        """

    def call(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 200,
        temperature: float = 0.3,
        cache_system_prompt: bool = False,
        json_output: bool = False
    ) -> LLMResponse:
        """
        Send a prompt to the LLM with automatic fallback.

        Fallback chain: Anthropic -> Ollama.
        If both fail, raises LLMUnavailableError.

        cache_system_prompt: if True and using Anthropic, adds
          cache_control breakpoint to the system message for
          prompt caching.
        json_output: if True, instructs the LLM to return valid
          JSON and parses/validates the response. Raises
          LLMJSONParseError if the response is not valid JSON.

        Returns: LLMResponse with text, provider info, token counts.
        """

    def check_ollama_connectivity(self) -> bool:
        """
        Ping Ollama at the configured host. Returns True if
        reachable, False otherwise. Used for startup health checks.
        """

class LLMUnavailableError(Exception):
    """Raised when all LLM providers fail."""
    pass

class LLMJSONParseError(Exception):
    """Raised when json_output=True but response is not valid JSON."""
    pass
```

### llm/prompt_loader.py

```python
class PromptLoader:
    def __init__(self, prompts_dir: str):
        """
        prompts_dir: absolute path to the consuming agent's
        prompts/ directory. This library ships no prompts.
        """

    def load(
        self,
        template_name: str,
        variables: dict[str, str] | None = None
    ) -> str:
        """
        Load a markdown template file and substitute variables.

        Template format: {variable_name} placeholders in the
        markdown file are replaced with values from the variables
        dict.

        template_name: filename (e.g., "card_name.md") relative
          to prompts_dir.
        variables: dict of placeholder -> value substitutions.

        Returns: the rendered prompt string.
        Raises: FileNotFoundError if template doesn't exist.
        Raises: KeyError if a placeholder has no matching variable.
        """
```

### models.py (top-level)

```python
@dataclass
class ProcessingResult:
    success: bool
    item_id: str                # Generic ID of the processed item
    action: str                 # What was done: "created", "moved", etc.
    details: dict = field(default_factory=dict)
    error_message: str | None = None
    timestamp: str = ""         # ISO 8601, set at creation if empty
```

## Risks and Mitigations
These are cross-cutting risks that should influence how every
submodule is built. Claude Code should build defensively against these.

### Interface Mismatch During Migration (Likelihood: High)
The primary risk: if the shared library's function signatures do
not exactly match the gmail-to-trello agent's existing calls,
migration will require test logic changes (which violates the
migration constraint).
- Mitigation: Clone the gmail-to-trello repo and inspect every
  call site before writing the shared library function. Match
  parameter names, return types, and error behavior exactly.
- Mitigation: The gmail-to-trello agent's 197 tests are the
  acceptance criteria. Run them after every migration phase.
- Mitigation: If a difference is discovered during migration,
  fix it in the shared library (add a compatibility shim), never
  in the test assertions.

### Config Path Resolution Across Agents (Likelihood: Medium)
Each agent lives in a different directory. The relative fallback
path (../config/.env.json) may resolve differently depending on
where the agent is run from.
- Mitigation: config_loader always tries ENV_CONFIG_PATH first.
  Document that agents should set this env var.
- Mitigation: The fallback relative path is resolved from
  os.getcwd(), which is the agent's repo root when run normally.
  Document this assumption.
- Mitigation: config_loader accepts an explicit config_path
  parameter as the highest-priority override for testing and
  non-standard setups.

### Trello API Rate Limits (Likelihood: Low)
Trello allows 100 requests per 10-second window per token. The
grooming agent reading cards across multiple lists could approach
this if lists are large.
- Mitigation: get_multiple_lists_cards makes one API call per
  list, not per card. For typical list sizes (50-200 cards), this
  is well within limits.
- Mitigation: On 429 responses, implement exponential backoff
  with a maximum of 3 retries before raising an exception.
- Mitigation: Log every API call at DEBUG level so rate limit
  issues are diagnosable.

### Anthropic API Unavailable (Likelihood: Low)
The Anthropic API could be unreachable, rate-limited, or the API
key could be invalid or missing.
- Mitigation: Automatic fallback to Ollama.
- Mitigation: LLMResponse.provider_used records which provider
  was actually used. The calling agent can log/record this.
- Mitigation: If anthropic_api_key is None or empty, Anthropic
  is silently skipped (not an error) and Ollama is tried first.

### Ollama Unavailable (Likelihood: Medium)
The Ollama service may not be running, may have crashed, or the
model may not be loaded.
- Mitigation: check_ollama_connectivity() lets the calling agent
  do a startup health check and log a warning.
- Mitigation: If both Anthropic and Ollama fail, LLMClient.call()
  raises LLMUnavailableError. The calling agent decides how to
  handle this (e.g., subject-line fallback for gmail-to-trello,
  skip-and-retry for grooming agent).

### Prompt Caching Behavior (Likelihood: Medium)
Anthropic's prompt caching has specific requirements: the cached
content must be marked with cache_control, and cache hits are not
guaranteed (depends on load, timing, content stability).
- Mitigation: cache_system_prompt is opt-in. The calling agent
  decides when caching is beneficial (e.g., same system prompt
  across many cards in a grooming batch).
- Mitigation: LLMResponse.cached indicates whether a cache hit
  occurred, enabling the caller to monitor cache effectiveness.
- Mitigation: If the Anthropic API rejects the cache_control
  parameter (API version mismatch), fall back to a non-cached
  call and log a warning.

### JSON Output Parsing (Likelihood: Medium)
When json_output=True, the LLM may return text that is not valid
JSON (markdown fences, prose before/after the JSON, trailing
commas).
- Mitigation: Strip markdown code fences (```json ... ```) and
  leading/trailing whitespace before parsing.
- Mitigation: If json.loads() fails, raise LLMJSONParseError
  with the raw text included so the caller can inspect it.
- Mitigation: The caller is responsible for validating the JSON
  schema. This library only guarantees syntactically valid JSON.

### SQLite Locking on Windows (Likelihood: Low)
SQLite on Windows with WAL mode can encounter locking issues if
multiple processes access the same DB file simultaneously.
- Mitigation: Each agent has its own DB file. The shared library's
  db.py does not reference any specific DB path; the caller passes
  it.
- Mitigation: db_connection context manager ensures connections
  are always closed, even on exceptions.
- Mitigation: WAL mode is enabled by default for better concurrent
  read performance, but each agent is expected to be a single
  process accessing its own DB.

## Testing Strategy
Five test categories per submodule, as defined in docs/testing.md:
1. Happy path: Normal operation with valid inputs.
2. Boundary/edge cases: Empty lists, max-length strings, zero
   results, single-item batches.
3. Graceful degradation: API failures, network timeouts, malformed
   responses from external services.
4. Bad input/validation: Missing required parameters, wrong types,
   empty strings where non-empty expected.
5. Idempotency/state: Calling the same function twice with the
   same input produces the same result. No hidden state leaks
   between calls.

All Trello API calls mocked via unittest.mock.patch on
requests.request or requests.get/post/put/delete.
All Anthropic API calls mocked via unittest.mock.patch on the
httpx or anthropic client.
All Ollama calls mocked via unittest.mock.patch on requests.post.
All file I/O in config_loader tests uses tmp_path fixtures.

## Future Scope (Do NOT Build Now)
The following are out of scope for the current build. Do not build
abstractions or frameworks for these. Just avoid hardcoding
decisions that would make them difficult later.

- Vector embedding submodule: The duplicate detection agent will
  need ChromaDB + Sentence Transformers for card similarity. This
  will be added as a new submodule (agent_shared.embeddings) when
  that agent is built. The current Trello submodule should not
  import or depend on embeddings.
- Webhook/event listener: Future agents may want real-time Trello
  or Gmail events instead of polling. The current library is
  pull-based only.
- Async support: All functions are synchronous. If a future agent
  needs async (e.g., processing many cards concurrently), async
  wrappers can be added without changing the sync interface.
- Multi-board support: TrelloClient currently takes a single
  board_id. Future agents operating across boards would need
  either multiple client instances or a board_id parameter on
  each method. Avoid hardcoding board_id into method signatures
  where it's not needed (card operations use card_id, which is
  globally unique).
- Notification/alerting submodule: Future agents may want Slack
  or email notifications on completion or failure. Not this
  library's concern; consuming agents handle their own side
  effects.
- Structured logging (JSON): Current logging uses plain text with
  rotating files. A future version could add JSON structured
  logging for better parsing. The logging_setup function signature
  supports this via future parameters without breaking existing
  callers.
