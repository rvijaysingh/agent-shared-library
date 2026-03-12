# Testing Strategy — agent-shared Library

## Philosophy

The test suite validates that every submodule fulfills its contract without making live API calls.
All external dependencies (Trello REST API, Anthropic SDK, Ollama HTTP, filesystem paths) are
either mocked or use `tmp_path` fixtures. Tests must run in under 5 seconds with no network access.

### Five Test Categories Applied to Every Submodule

1. **Happy path** — Normal operation with valid inputs; verify correct return type and values.
2. **Boundary/edge cases** — Empty lists, zero values, maximum-length strings, single-item
   batches, None vs. empty string, dict vs. scalar required fields.
3. **Graceful degradation** — API failures (4xx, 5xx, timeouts), missing files, invalid JSON.
4. **Bad input/validation** — Missing required parameters, wrong types, empty strings where
   non-empty expected, JSON parse failures.
5. **Idempotency/state** — Calling the same function twice gives the same result. No hidden
   state leaks between calls or across test functions.

---

## How to Run Tests

```bash
# Run all tests, stop at first failure
pytest tests/ -x

# Run all tests with verbose output
pytest tests/ -v --tb=short

# Run a single test file
pytest tests/test_trello_client.py -v

# Run a single test class or function
pytest tests/test_trello_client.py::TestCreateCard -v
pytest tests/test_llm_client.py::test_fallback_anthropic_exception_uses_ollama -v

# Run with coverage (requires pytest-cov)
pytest --cov=agent_shared tests/

# Run integration tests only
pytest tests/test_integration.py -v
```

---

## Mocking Patterns

### Trello API (requests.request)
All Trello REST calls go through `TrelloClient._request()`, which calls `requests.request()`
directly. Mock at the module level:

```python
from unittest.mock import patch, MagicMock
import requests

def make_response(status_code: int = 200, body=None) -> MagicMock:
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body or {}
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp

with patch("requests.request", return_value=make_response(200, {"id": "card_123"})):
    result = client.create_card(list_id, name, desc)
```

### Anthropic SDK (anthropic.Anthropic)
The `LLMClient` instantiates `anthropic.Anthropic(api_key=...)` inside `_call_anthropic`.
Mock the class constructor:

```python
ANTHROPIC_PATCH = "agent_shared.llm.client.anthropic.Anthropic"

mock_class = MagicMock()
mock_instance = MagicMock()
mock_class.return_value = mock_instance

block = MagicMock()
block.type = "text"
block.text = "response text"
mock_response = MagicMock()
mock_response.content = [block]
mock_response.usage.input_tokens = 100
mock_response.usage.output_tokens = 20
mock_response.usage.cache_read_input_tokens = 0
mock_instance.messages.create.return_value = mock_response

with patch(ANTHROPIC_PATCH, mock_class):
    result = client.call("prompt")
```

### Ollama (requests.post)
The `LLMClient._call_ollama` uses `requests.post` directly. Mock at the module path:

```python
REQUESTS_POST_PATCH = "agent_shared.llm.client.requests.post"

mock_resp = MagicMock(spec=requests.Response)
mock_resp.status_code = 200
mock_resp.json.return_value = {"response": "task name", "done": True}
mock_resp.raise_for_status.return_value = None

with patch(REQUESTS_POST_PATCH, return_value=mock_resp):
    result = client.call("prompt")
```

### Ollama Connectivity Check (requests.get)
```python
REQUESTS_GET_PATCH = "agent_shared.llm.client.requests.get"

with patch(REQUESTS_GET_PATCH, return_value=MagicMock(status_code=200)):
    assert client.check_ollama_connectivity() is True
```

### Filesystem (tmp_path)
`config_loader` and `prompt_loader` read from disk. Use pytest's `tmp_path` fixture:

```python
def test_something(tmp_path):
    cfg_file = tmp_path / ".env.json"
    cfg_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    result = load_config(config_path=str(cfg_file))
```

---

## Fixture Inventory

All fixture files live in `tests/fixtures/`.

| File | Purpose |
|------|---------|
| `sample_env.json` | Valid global config used by integration tests and config_loader tests. Contains all six standard fields including `anthropic_api_keys` dict with two agent keys. |
| `trello_responses/card_create_response.json` | Trello API response for POST /cards. Contains `id`, `url`, `shortUrl`, `name`, `labels: []`, `due: null`. Used by create_card, get_card (no-label/no-due-date cases), move_card, update_card tests. |
| `trello_responses/card_get_response.json` | Trello API response for GET /cards/{id}. Contains a card with one label (Backend/blue), a due date, and a list_id. Used by get_card happy path tests. |
| `trello_responses/list_cards_response.json` | Trello API response for GET /lists/{id}/cards. Array of two cards; card[0] has no labels, card[1] has one label. Used by get_list_cards and get_multiple_lists_cards tests. |
| `trello_responses/board_labels_response.json` | Array of 4 labels with varied colors (blue, red, green, null). Used by get_board_labels tests including color-None case. |
| `trello_responses/board_lists_response.json` | Array of 3 lists (Inbox, Backlog, Today) with ids, positions. Used by get_board_lists and validate_list_exists tests. |
| `trello_responses/card_actions_response.json` | Array of card action objects. Used by get_card_actions tests. |
| `llm_responses/ollama_generate_response.json` | Ollama /api/generate response with plain text. Unused by current tests (tests build mocks inline) but available for future fixture-based tests. |
| `llm_responses/ollama_generate_json_response.json` | Ollama response with JSON string in `response` field. Unused by current tests but available for fixture-based tests. |

---

## Test Case Table

### test_config_loader.py (15 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_load_config_valid_returns_dict` | Happy path | Valid file loads, returns plain dict with correct values |
| `test_load_config_required_fields_all_present` | Happy path | Required field validation passes when all fields present |
| `test_load_config_no_required_fields_loads_all` | Boundary | None required_fields loads all fields without validation |
| `test_load_config_required_fields_empty_list` | Boundary | Empty required_fields list skips validation |
| `test_load_config_dict_value_is_valid` | Boundary | Non-string required field (dict) that is non-empty passes validation |
| `test_load_config_integer_zero_passes_validation` | Boundary | Integer 0 is a valid non-empty value |
| `test_load_config_missing_file_raises_file_not_found` | Degradation | FileNotFoundError when config file absent |
| `test_load_config_invalid_json_raises_json_decode_error` | Degradation | json.JSONDecodeError on malformed JSON |
| `test_load_config_missing_required_field_raises_error` | Bad input | ConfigValidationError when required field absent |
| `test_load_config_empty_string_required_field_raises_error` | Bad input | ConfigValidationError when required field is "" |
| `test_load_config_none_required_field_raises_error` | Bad input | ConfigValidationError when required field is null |
| `test_load_config_env_config_path_override` | Idempotency | ENV_CONFIG_PATH env var used when no config_path given |
| `test_load_config_explicit_path_overrides_env_var` | Idempotency | Explicit config_path takes priority over ENV_CONFIG_PATH |
| `test_load_config_relative_fallback_path` | Idempotency | Fallback to ../config/.env.json relative to cwd |
| `test_load_config_called_twice_same_file_returns_same_data` | Idempotency | Two loads return equal but distinct dicts (no caching) |

### test_logging_setup.py (10 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_setup_logging_returns_logger_with_correct_name` | Happy path | Returns Logger instance with given name |
| `test_setup_logging_creates_log_file` | Happy path | Log file created on disk after first write |
| `test_setup_logging_writes_messages_to_file` | Happy path | INFO messages appear in file; DEBUG messages suppressed |
| `test_setup_logging_default_level_is_info` | Happy path | Default log level is INFO |
| `test_setup_logging_creates_parent_directories` | Boundary | Parent directories created automatically |
| `test_setup_logging_custom_log_level` | Boundary | Custom DEBUG level applied to logger and handler |
| `test_setup_logging_rotating_handler_max_bytes` | Boundary | RotatingFileHandler configured with given max_bytes |
| `test_setup_logging_idempotent_same_name_clears_old_handlers` | Degradation | Second call with same name has exactly 1 handler |
| `test_setup_logging_unique_names_dont_share_handlers` | Bad input | Two loggers with different names have independent handlers |
| `test_setup_logging_second_call_writes_to_new_file` | Idempotency | Re-calling with same name reroutes to new file |

### test_db.py (17 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_get_db_connection_returns_connection` | Happy path | Returns valid sqlite3.Connection |
| `test_get_db_connection_wal_mode_enabled` | Happy path | WAL journal mode enabled |
| `test_get_db_connection_foreign_keys_enabled` | Happy path | Foreign key enforcement enabled |
| `test_get_db_connection_row_factory_is_sqlite_row` | Happy path | Columns accessible by name via sqlite3.Row |
| `test_table_exists_returns_true_for_existing_table` | Happy path | Returns True after CREATE TABLE |
| `test_ensure_table_creates_table` | Happy path | ensure_table executes CREATE TABLE IF NOT EXISTS |
| `test_ensure_table_allows_insert_after_creation` | Happy path | Table accepts INSERT after ensure_table |
| `test_table_exists_returns_false_for_missing_table` | Boundary | Returns False for uncreated table |
| `test_ensure_table_is_idempotent` | Boundary | Two calls with same SQL do not raise |
| `test_get_db_connection_creates_parent_directories` | Boundary | Parent directories created automatically |
| `test_db_connection_rolls_back_on_exception` | Degradation | Context manager rolls back INSERT on exception |
| `test_db_connection_re_raises_exception` | Degradation | Context manager re-raises original exception |
| `test_table_exists_case_sensitive` | Bad input | "Items" != "items" in sqlite_master |
| `test_check_constraint_validated_at_insert_not_create` | Bad input | CHECK constraints fire at INSERT, not CREATE TABLE |
| `test_db_connection_commits_on_success` | Idempotency | Context manager commits on clean exit |
| `test_db_connection_closes_connection_after_success` | Idempotency | Connection closed after successful exit |
| `test_db_connection_closes_connection_after_exception` | Idempotency | Connection closed even when exception raised |

### test_models.py (11 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_llm_response_required_fields` | Happy path | text and provider_used required; all others default |
| `test_llm_response_all_fields` | Happy path | All fields stored correctly when provided |
| `test_llm_response_cached_defaults_false` | Boundary | cached defaults to False |
| `test_llm_response_equality` | Boundary | Two instances with same fields are equal |
| `test_processing_result_auto_timestamp_when_empty` | Happy path | Auto-populates ISO 8601 UTC timestamp |
| `test_processing_result_explicit_timestamp_preserved` | Happy path | Non-empty timestamp not overwritten |
| `test_processing_result_required_fields` | Happy path | success, item_id, action required; defaults correct |
| `test_processing_result_all_fields` | Happy path | All fields stored correctly |
| `test_processing_result_default_details_are_independent` | Boundary | Two instances have independent details dicts |
| `test_processing_result_error_message_stored` | Boundary | error_message stored when provided |
| `test_processing_result_timestamp_is_utc_iso8601` | Idempotency | Auto timestamp contains UTC offset |

### test_trello_models.py (14 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_trello_label_required_fields` | Happy path | id and name required; color defaults None |
| `test_trello_label_with_color` | Happy path | color stored when provided |
| `test_trello_label_color_none_is_default` | Boundary | color is None by default |
| `test_trello_label_equality` | Boundary | Two TrelloLabel instances with same fields are equal |
| `test_trello_card_required_fields_only` | Happy path | id and name required; all others default |
| `test_trello_card_all_fields` | Happy path | All fields stored correctly including nested labels |
| `test_trello_card_with_no_labels` | Boundary | Empty labels list is valid |
| `test_trello_card_with_multiple_labels` | Boundary | Holds multiple TrelloLabel instances |
| `test_trello_card_closed_flag` | Boundary | closed=True stored correctly |
| `test_trello_card_default_labels_are_independent` | Idempotency | Two cards have independent labels lists |
| `test_trello_card_equality` | Idempotency | Two TrelloCard instances with same fields are equal |
| `test_trello_list_required_fields_only` | Happy path | id and name required; closed/position default |
| `test_trello_list_all_fields` | Happy path | All TrelloList fields stored correctly |
| `test_trello_list_equality` | Idempotency | Two TrelloList instances with same fields are equal |

### test_trello_client.py (44 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `TestCreateCard::test_create_card_returns_dict_with_id_and_url` | Happy path | Returns raw dict with id and url keys |
| `TestCreateCard::test_create_card_sends_correct_list_id` | Happy path | idList sent correctly in request body |
| `TestCreateCard::test_create_card_sends_name_and_desc` | Happy path | name and desc mapped from Python params |
| `TestCreateCard::test_create_card_defaults_position_to_top` | Happy path | pos="top" sent by default |
| `TestCreateCard::test_create_card_sends_auth_in_query_params` | Happy path | key/token sent as query params |
| `TestCreateCard::test_create_card_posts_to_cards_endpoint` | Happy path | POST to /cards endpoint |
| `TestCreateCard::test_create_card_with_label_ids` | Happy path | Label IDs included in body when provided |
| `TestGetCard::test_get_card_returns_trello_card` | Happy path | Returns TrelloCard dataclass |
| `TestGetCard::test_get_card_parses_labels` | Happy path | Labels populated as TrelloLabel objects |
| `TestGetCard::test_get_card_parses_due_date` | Happy path | due_date populated from API |
| `TestGetListCards::test_get_list_cards_returns_list_of_trello_cards` | Happy path | Returns list of TrelloCard objects |
| `TestGetListCards::test_get_list_cards_parses_card_fields` | Happy path | TrelloCard fields populated correctly |
| `TestGetBoardLabels::test_get_board_labels_returns_trello_label_list` | Happy path | Returns list of TrelloLabel objects |
| `TestGetBoardLabels::test_get_board_labels_parses_color` | Happy path | Color populated including None |
| `TestGetBoardLists::test_get_board_lists_returns_trello_list_objects` | Happy path | Returns list of TrelloList objects |
| `TestGetBoardLists::test_get_board_lists_parses_fields` | Happy path | TrelloList fields populated correctly |
| `TestMoveCard::test_move_card_sends_correct_params` | Happy path | idList and pos sent in body |
| `TestMoveCard::test_move_card_returns_dict` | Happy path | Returns raw dict |
| `TestUpdateCard::test_update_card_sends_only_non_none_params` | Bad input | None params omitted from body |
| `TestUpdateCard::test_update_card_all_fields` | Happy path | All fields sent when all specified |
| `TestAddComment::test_add_comment_posts_correct_text` | Happy path | text sent to /comments endpoint |
| `TestGetMultipleListsCards::test_get_multiple_lists_cards_returns_dict_of_lists` | Happy path | Dict maps list_id to TrelloCard list |
| `TestValidateListExists::test_validate_list_exists_returns_true_for_known_id` | Happy path | True for existing list |
| `TestValidateListExists::test_validate_list_exists_returns_false_for_unknown_id` | Happy path | False for unknown list |
| `test_get_list_cards_empty_list` | Boundary | Empty API response returns empty list |
| `test_get_list_cards_single_card` | Boundary | Single-card response handled correctly |
| `test_get_card_with_no_labels` | Boundary | TrelloCard.labels=[] when API returns no labels |
| `test_get_card_with_no_due_date` | Boundary | due_date=None when API returns null |
| `test_get_card_actions_with_limit` | Boundary | limit param sent as query param |
| `test_update_card_single_field_only` | Boundary | Only one key in body when one field specified |
| `test_rate_limit_retries_then_succeeds` | Degradation | 429→retry→200: one sleep, correct result |
| `test_rate_limit_retries_multiple_then_succeeds` | Degradation | 429→429→200: two sleeps (1s, 2s) |
| `test_rate_limit_exhausts_retries_and_raises` | Degradation | Three 429s raise HTTPError after 1s/2s/4s sleeps |
| `test_server_error_raises_http_error` | Degradation | 500 raises HTTPError immediately (no retry) |
| `test_network_timeout_raises` | Degradation | Timeout raises requests.Timeout |
| `test_connection_error_raises` | Degradation | ConnectionError propagates |
| `test_unauthorized_raises_http_error` | Degradation | 401 raises HTTPError without retry |
| `test_update_card_no_fields_sends_empty_body` | Bad input | All-None update sends empty body {} |
| `test_create_card_empty_description_is_valid` | Bad input | Empty desc="" is not an error |
| `test_get_list_cards_include_closed_sends_filter_all` | Bad input | include_closed=True sends filter=all |
| `test_get_list_cards_exclude_closed_sends_no_filter` | Bad input | Default (False) sends no filter param |
| `test_client_is_reusable_across_calls` | Idempotency | Client makes multiple calls without state corruption |
| `test_get_list_cards_called_twice_returns_same_results` | Idempotency | Two calls give identical results |
| `test_get_multiple_lists_cards_makes_one_call_per_list` | Idempotency | Exactly one API call per list_id |

### test_llm_client.py (42 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_anthropic_success_returns_llm_response` | Happy path | Returns LLMResponse dataclass on Anthropic success |
| `test_anthropic_provider_used_is_anthropic` | Happy path | provider_used="anthropic" on Anthropic path |
| `test_anthropic_token_counts_populated` | Happy path | tokens_in/tokens_out populated from usage |
| `test_anthropic_cached_true_when_cache_read_tokens_nonzero` | Happy path | cached=True when cache_read_input_tokens > 0 |
| `test_anthropic_cached_false_when_no_cache_hit` | Happy path | cached=False when cache_read_input_tokens=0 |
| `test_anthropic_model_name_in_response` | Happy path | model field reflects configured anthropic_model |
| `test_ollama_success_returns_llm_response` | Happy path | Returns LLMResponse with provider_used="ollama" |
| `test_ollama_model_name_in_response` | Happy path | model field reflects configured ollama_model |
| `test_fallback_anthropic_exception_uses_ollama` | Happy path | Anthropic exception triggers Ollama fallback |
| `test_system_prompt_passed_to_anthropic` | Happy path | system_prompt included in Anthropic call |
| `test_system_prompt_passed_to_ollama` | Happy path | system_prompt included in Ollama POST body |
| `test_cache_system_prompt_sends_cache_control` | Happy path | cache_system_prompt=True adds cache_control block |
| `test_json_output_returns_valid_json_string` | Happy path | json_output=True validates and returns JSON text |
| `test_json_output_strips_markdown_fences` | Happy path | ```json fences stripped before parsing |
| `test_json_output_appends_instruction_to_prompt` | Happy path | JSON-only instruction appended to prompt |
| `test_empty_prompt_is_accepted` | Boundary | Empty string prompt does not raise before LLM |
| `test_very_long_prompt_is_accepted` | Boundary | 10000+ char prompt accepted |
| `test_empty_anthropic_api_key_skips_to_ollama` | Boundary | Empty string api_key skips Anthropic |
| `test_none_anthropic_api_key_skips_to_ollama` | Boundary | None api_key skips Anthropic |
| `test_json_output_with_plain_fences_strips_correctly` | Boundary | ``` (no json tag) fences stripped |
| `test_ollama_stream_false_in_request_body` | Boundary | stream=False always in Ollama body |
| `test_both_providers_fail_raises_llm_unavailable_error` | Degradation | Both fail raises LLMUnavailableError |
| `test_anthropic_only_fails_with_no_key_and_ollama_down` | Degradation | No key + Ollama failure = LLMUnavailableError |
| `test_anthropic_specific_exception_type_triggers_fallback` | Degradation | ValueError from Anthropic triggers fallback |
| `test_ollama_500_raises_llm_unavailable` | Degradation | Ollama 500 propagates as LLMUnavailableError |
| `test_json_output_non_json_response_raises_llm_json_parse_error` | Bad input | Non-JSON response raises LLMJSONParseError |
| `test_llm_json_parse_error_includes_raw_text` | Bad input | raw_text attribute contains original response |
| `test_json_parse_error_does_not_fall_back_to_ollama` | Bad input | LLMJSONParseError does NOT trigger Ollama fallback |
| `test_no_system_prompt_not_sent_to_anthropic` | Bad input | None system_prompt omits system kwarg |
| `test_no_system_prompt_not_sent_to_ollama` | Bad input | None system_prompt omits system key in body |
| `test_call_twice_returns_consistent_results` | Idempotency | Two calls with same inputs give consistent results |
| `test_client_credentials_unchanged_after_call` | Idempotency | Credentials not mutated by call() |
| `test_check_ollama_connectivity_returns_true_on_200` | Happy path | Returns True on HTTP 200 |
| `test_check_ollama_connectivity_returns_false_on_non_200` | Degradation | Returns False on non-200 |
| `test_check_ollama_connectivity_returns_false_on_connection_error` | Degradation | Returns False on ConnectionError |
| `test_check_ollama_connectivity_returns_false_on_timeout` | Degradation | Returns False on Timeout |
| `test_check_ollama_connectivity_pings_correct_endpoint` | Happy path | GETs /api/tags on configured host |

### test_prompt_loader.py (15 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `test_load_substitutes_single_variable` | Happy path | {name} placeholder replaced with value |
| `test_load_substitutes_multiple_variables` | Happy path | All {key} placeholders replaced |
| `test_load_with_none_variables_returns_raw_content` | Happy path | variables=None returns template unchanged |
| `test_load_returns_full_file_content` | Happy path | Complete file content including whitespace |
| `test_load_no_placeholders_with_empty_variables` | Boundary | No placeholders + empty dict returns content unchanged |
| `test_load_no_placeholders_with_extra_variables` | Boundary | Extra keys in variables silently ignored |
| `test_load_multiple_occurrences_of_same_placeholder` | Boundary | All occurrences of same {key} replaced |
| `test_load_template_with_multiline_content` | Boundary | Multi-line templates handled correctly |
| `test_load_missing_file_raises_file_not_found` | Degradation | FileNotFoundError when template absent |
| `test_load_missing_file_error_message_includes_path` | Degradation | Error message includes path to missing file |
| `test_load_missing_variable_raises_key_error` | Bad input | KeyError when placeholder has no matching variable |
| `test_load_completely_empty_variables_with_placeholders_raises_key_error` | Bad input | Empty dict + template with placeholders raises KeyError |
| `test_load_same_template_twice_returns_same_result` | Idempotency | Two loads return identical strings |
| `test_loader_does_not_cache_between_calls` | Idempotency | Re-reads file; file modifications reflected |
| `test_loader_instance_reusable_for_different_templates` | Idempotency | One PromptLoader loads different templates |

### test_integration.py (7 tests)

| Test Function | Category | Description |
|---------------|----------|-------------|
| `TestGmailToTrelloUsagePattern::test_config_load_and_trello_card_creation` | Happy path | Load sample_env.json, create TrelloClient, mock create_card, verify id/url in result |
| `TestGmailToTrelloUsagePattern::test_config_load_and_llm_call_with_fallback` | Degradation | Load config, fail Anthropic, succeed Ollama, verify provider_used="ollama" |
| `TestGmailToTrelloUsagePattern::test_full_pipeline_simulation` | Happy path | LLM (mocked) → Trello card (mocked) → SQLite insert → query verify |
| `TestGroomingAgentUsagePattern::test_read_cards_across_lists` | Happy path | get_multiple_lists_cards with 3 list IDs returns dict with 3 keys |
| `TestGroomingAgentUsagePattern::test_llm_scoring_with_json_output` | Happy path | Mocked Anthropic returns JSON, json_output=True parses it |
| `TestGroomingAgentUsagePattern::test_card_move_and_label_update` | Happy path | move_card and update_card called with correct params |
| `TestGroomingAgentUsagePattern::test_card_comment_and_activity` | Happy path | add_comment and get_card_actions verified |

---

## Guidelines for Adding New Tests

1. **Name tests**: `test_{function}_{scenario}_{expected_result}` — e.g.,
   `test_create_card_with_closed_true_archives_card`.

2. **One assertion per test is ideal**, but related assertions (e.g., checking both `id` and
   `url` in the same response) may be grouped in one test.

3. **Never use live APIs**. If a test requires network access, it is wrong. Add a mock.

4. **Add fixture files** for new API responses to `tests/fixtures/trello_responses/` or
   `tests/fixtures/llm_responses/`. Name them descriptively: `card_archive_response.json`.

5. **Use unique logger names** in any test that calls `setup_logging`. Append the test function
   name to avoid global logger state pollution (see LESSONS.md).

6. **Mock at the correct path**. For Trello, mock `requests.request`. For Anthropic, mock
   `agent_shared.llm.client.anthropic.Anthropic`. For Ollama, mock
   `agent_shared.llm.client.requests.post`. Do not mock at the external library path.

7. **Add all five categories** for any new submodule. Do not add a submodule with only happy
   path tests.
