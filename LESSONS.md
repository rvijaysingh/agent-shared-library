# LESSONS.md — Operational Findings

Seeded from the gmail-to-trello agent and updated as new findings emerge during development
of agent-shared and consuming agents. Read this before making any changes.

## Trello

### Markdown List Rendering on Mobile
Trello mobile renders markdown "- " list items in large font (heading-like). Use the unicode
bullet character "•" (U+2022) instead of "- " for list items in card descriptions to get
consistent small-font rendering across web and mobile.

### Card Description Character Limit
Trello card descriptions have a hard limit of 16,384 characters. The API returns a 400 error
if you exceed this. Truncate descriptions before calling create_card or update_card. Include
a truncation notice at the end so the card is not silently incomplete.

## Anthropic API

### Token Usage Fields
The Anthropic API returns token usage in `response.usage.input_tokens` and
`response.usage.output_tokens`. These are integers. The field names are NOT `prompt_tokens`
or `completion_tokens` (those are OpenAI's names). Do not conflate the two.

### Prompt Caching
Prompt caching requires `cache_control` to be set on the system message content block with
`{"type": "ephemeral"}`. Cache hits are not guaranteed and depend on Anthropic's infrastructure
load and the stability of the cached content. Always check `response.usage.cache_read_input_tokens`
to confirm a cache hit occurred before reporting it as cached.

## Ollama

### API Endpoint Format
The Ollama `/api/generate` endpoint expects a JSON body with exactly:
`{"model": "...", "prompt": "...", "stream": false}`. Setting `stream` to `false` is required
to get a single JSON response rather than a streaming response split across multiple lines.
Omitting `stream` defaults to streaming mode, which will break JSON parsing of the response.

## SQLite

### CHECK Constraints Timing
SQLite CHECK constraints are validated at INSERT time, not at CREATE TABLE time. A table with
an invalid CHECK constraint (e.g., referencing a non-existent column) will be created without
error but fail at first insert. Always test schema correctness with actual INSERT statements,
not just `CREATE TABLE` calls.

## Config Loading

### Path Resolution Order
Config path resolution must handle both `ENV_CONFIG_PATH` environment variable and the relative
fallback `../config/.env.json`. Tests must cover both cases explicitly. The relative path is
resolved from `os.getcwd()`, which is the agent's repo root when run normally. Do not assume
the script's `__file__` location is the same as cwd.

## Python Logging

### Logger Instance Reuse
`logging.getLogger(name)` returns the same instance for the same name across the entire
process. If a test sets up handlers on a logger and the next test calls `getLogger` with the
same name, it will inherit those handlers, causing duplicate log output or unexpected state.
Always use unique logger names per test (e.g., append the test function name), or explicitly
clear handlers in teardown.
