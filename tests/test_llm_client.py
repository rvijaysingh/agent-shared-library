"""Tests for llm/client.py.

All Anthropic SDK calls are mocked via patch("agent_shared.llm.client.anthropic.Anthropic").
All Ollama HTTP calls are mocked via patch("agent_shared.llm.client.requests.post").
check_ollama_connectivity uses patch("agent_shared.llm.client.requests.get").
Zero live API calls are made.

Five categories:
1. Happy path — Anthropic success, Ollama success, fallback, json_output, cache, system_prompt
2. Boundary/edge — empty prompt, long prompt, json fences, empty api_key, None api_key
3. Graceful degradation — Anthropic fail + Ollama success, both fail, bad Ollama JSON
4. Bad input — json_output with non-JSON response raises LLMJSONParseError
5. Idempotency/state — call() twice gives same result, client has no hidden state
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from agent_shared.llm.client import LLMClient, LLMJSONParseError, LLMUnavailableError
from agent_shared.models import LLMResponse

FIXTURES = Path(__file__).parent / "fixtures" / "llm_responses"

ANTHROPIC_KEY = "sk-ant-test-key-001"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"
ANTHROPIC_MODEL = "claude-haiku-4-5-20241022"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_client(
    anthropic_api_key: str | None = ANTHROPIC_KEY,
    ollama_host: str = OLLAMA_HOST,
    ollama_model: str = OLLAMA_MODEL,
    anthropic_model: str = ANTHROPIC_MODEL,
) -> LLMClient:
    return LLMClient(
        anthropic_api_key=anthropic_api_key,
        ollama_host=ollama_host,
        ollama_model=ollama_model,
        anthropic_model=anthropic_model,
    )


def make_anthropic_mock(
    text: str = "Review Q3 board deck",
    tokens_in: int = 120,
    tokens_out: int = 15,
    cache_read: int = 0,
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_class, mock_messages_client) for patching anthropic.Anthropic."""
    mock_class = MagicMock()
    mock_instance = MagicMock()
    mock_class.return_value = mock_instance

    block = MagicMock()
    block.type = "text"
    block.text = text

    mock_response = MagicMock()
    mock_response.content = [block]
    mock_response.usage.input_tokens = tokens_in
    mock_response.usage.output_tokens = tokens_out
    mock_response.usage.cache_read_input_tokens = cache_read

    mock_instance.messages.create.return_value = mock_response
    return mock_class, mock_instance


def make_ollama_mock(text: str = "Review Q3 board deck", status: int = 200) -> MagicMock:
    """Return a mock requests.Response for Ollama POST."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status
    mock_resp.json.return_value = {
        "model": OLLAMA_MODEL,
        "response": text,
        "done": True,
    }
    if status >= 400:
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


ANTHROPIC_PATCH = "agent_shared.llm.client.anthropic.Anthropic"
REQUESTS_POST_PATCH = "agent_shared.llm.client.requests.post"
REQUESTS_GET_PATCH = "agent_shared.llm.client.requests.get"


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_anthropic_success_returns_llm_response():
    """A successful Anthropic call returns an LLMResponse dataclass."""
    mock_class, _ = make_anthropic_mock(text="Schedule board meeting")
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("Write a task name for this email")
    assert isinstance(result, LLMResponse)
    assert result.text == "Schedule board meeting"


def test_anthropic_provider_used_is_anthropic():
    """Anthropic path sets provider_used='anthropic'."""
    mock_class, _ = make_anthropic_mock()
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt")
    assert result.provider_used == "anthropic"


def test_anthropic_token_counts_populated():
    """Token counts from response.usage are stored in LLMResponse."""
    mock_class, _ = make_anthropic_mock(tokens_in=200, tokens_out=30)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt")
    assert result.tokens_in == 200
    assert result.tokens_out == 30


def test_anthropic_cached_true_when_cache_read_tokens_nonzero():
    """LLMResponse.cached=True when Anthropic reports cache_read_input_tokens > 0."""
    mock_class, _ = make_anthropic_mock(tokens_in=50, cache_read=150)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt", cache_system_prompt=True)
    assert result.cached is True


def test_anthropic_cached_false_when_no_cache_hit():
    """LLMResponse.cached=False when cache_read_input_tokens=0."""
    mock_class, _ = make_anthropic_mock(cache_read=0)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt")
    assert result.cached is False


def test_anthropic_model_name_in_response():
    """LLMResponse.model reflects the configured anthropic_model."""
    mock_class, _ = make_anthropic_mock()
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client(anthropic_model="claude-haiku-4-5-20241022").call("prompt")
    assert result.model == "claude-haiku-4-5-20241022"


def test_ollama_success_returns_llm_response():
    """A successful Ollama call returns an LLMResponse with provider_used='ollama'."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock("Follow up with Bob")):
        result = make_client(anthropic_api_key=None).call("prompt")
    assert isinstance(result, LLMResponse)
    assert result.text == "Follow up with Bob"
    assert result.provider_used == "ollama"


def test_ollama_model_name_in_response():
    """LLMResponse.model reflects the configured ollama_model for Ollama calls."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock()):
        result = make_client(anthropic_api_key=None, ollama_model="qwen3:8b").call("prompt")
    assert result.model == "qwen3:8b"


def test_fallback_anthropic_exception_uses_ollama():
    """When Anthropic raises an exception, Ollama is tried and returns a result."""
    mock_class = MagicMock()
    mock_class.return_value.messages.create.side_effect = Exception("Connection failed")

    with patch(ANTHROPIC_PATCH, mock_class):
        with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock("Ollama fallback text")):
            result = make_client().call("prompt")

    assert result.provider_used == "ollama"
    assert result.text == "Ollama fallback text"


def test_system_prompt_passed_to_anthropic():
    """System prompt is included in the Anthropic messages.create() call."""
    mock_class, mock_instance = make_anthropic_mock()
    with patch(ANTHROPIC_PATCH, mock_class):
        make_client().call("user prompt", system_prompt="You are a task manager")
    kwargs = mock_instance.messages.create.call_args.kwargs
    assert kwargs["system"] == "You are a task manager"


def test_system_prompt_passed_to_ollama():
    """System prompt is included in the Ollama POST body."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock()) as mock_post:
        make_client(anthropic_api_key=None).call("user prompt", system_prompt="Be concise")
    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["system"] == "Be concise"


def test_cache_system_prompt_sends_cache_control():
    """cache_system_prompt=True wraps system content with cache_control block."""
    mock_class, mock_instance = make_anthropic_mock()
    with patch(ANTHROPIC_PATCH, mock_class):
        make_client().call(
            "prompt",
            system_prompt="You are a task manager",
            cache_system_prompt=True,
        )
    kwargs = mock_instance.messages.create.call_args.kwargs
    system_block = kwargs["system"]
    assert isinstance(system_block, list)
    assert system_block[0]["cache_control"] == {"type": "ephemeral"}
    assert system_block[0]["text"] == "You are a task manager"


def test_json_output_returns_valid_json_string():
    """json_output=True validates JSON and returns the text unchanged if valid."""
    json_text = '{"action": "review", "subject": "Q3 deck"}'
    mock_class, _ = make_anthropic_mock(text=json_text)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt", json_output=True)
    # Must be parseable
    parsed = json.loads(result.text)
    assert parsed["action"] == "review"


def test_json_output_strips_markdown_fences():
    """json_output=True strips ```json ... ``` fences before parsing."""
    raw_with_fences = '```json\n{"key": "value"}\n```'
    mock_class, _ = make_anthropic_mock(text=raw_with_fences)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt", json_output=True)
    parsed = json.loads(result.text)
    assert parsed["key"] == "value"


def test_json_output_appends_instruction_to_prompt():
    """json_output=True adds JSON-only instruction to the prompt sent to the LLM."""
    mock_class, mock_instance = make_anthropic_mock(text='{"x": 1}')
    with patch(ANTHROPIC_PATCH, mock_class):
        make_client().call("Generate a task", json_output=True)
    sent_prompt = mock_instance.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "valid JSON only" in sent_prompt
    assert "No markdown fences" in sent_prompt


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_empty_prompt_is_accepted():
    """call() with an empty string prompt does not raise before reaching the LLM."""
    mock_class, _ = make_anthropic_mock(text="response")
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("")
    assert result.text == "response"


def test_very_long_prompt_is_accepted():
    """call() with a 10000+ char prompt does not raise before reaching the LLM."""
    long_prompt = "x" * 10_001
    mock_class, _ = make_anthropic_mock(text="response")
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call(long_prompt)
    assert isinstance(result, LLMResponse)


def test_empty_anthropic_api_key_skips_to_ollama():
    """Empty string api_key skips Anthropic entirely; Ollama is called."""
    with patch(ANTHROPIC_PATCH) as mock_class:
        with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock("ollama result")):
            result = make_client(anthropic_api_key="").call("prompt")
    mock_class.assert_not_called()
    assert result.provider_used == "ollama"


def test_none_anthropic_api_key_skips_to_ollama():
    """None api_key is treated the same as empty string — skips Anthropic."""
    with patch(ANTHROPIC_PATCH) as mock_class:
        with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock("result")):
            result = make_client(anthropic_api_key=None).call("prompt")
    mock_class.assert_not_called()
    assert result.provider_used == "ollama"


def test_json_output_with_plain_fences_strips_correctly():
    """json_output=True handles ``` (no json tag) fences correctly."""
    raw = '```\n{"a": 1}\n```'
    mock_class, _ = make_anthropic_mock(text=raw)
    with patch(ANTHROPIC_PATCH, mock_class):
        result = make_client().call("prompt", json_output=True)
    assert json.loads(result.text) == {"a": 1}


def test_ollama_stream_false_in_request_body():
    """Ollama request always includes stream=False to avoid streaming mode."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock()) as mock_post:
        make_client(anthropic_api_key=None).call("prompt")
    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["stream"] is False


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------

def test_both_providers_fail_raises_llm_unavailable_error():
    """When both Anthropic and Ollama fail, LLMUnavailableError is raised."""
    mock_class = MagicMock()
    mock_class.return_value.messages.create.side_effect = Exception("Anthropic down")

    with patch(ANTHROPIC_PATCH, mock_class):
        with patch(
            REQUESTS_POST_PATCH,
            side_effect=requests.exceptions.ConnectionError("Ollama down"),
        ):
            with pytest.raises(LLMUnavailableError):
                make_client().call("prompt")


def test_anthropic_only_fails_with_no_key_and_ollama_down():
    """No Anthropic key + Ollama failure = LLMUnavailableError."""
    with patch(
        REQUESTS_POST_PATCH,
        side_effect=requests.exceptions.Timeout("timeout"),
    ):
        with pytest.raises(LLMUnavailableError):
            make_client(anthropic_api_key=None).call("prompt")


def test_anthropic_specific_exception_type_triggers_fallback():
    """Any exception type from Anthropic (not just network errors) triggers fallback."""
    mock_class = MagicMock()
    mock_class.return_value.messages.create.side_effect = ValueError("unexpected")

    with patch(ANTHROPIC_PATCH, mock_class):
        with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock("fallback")):
            result = make_client().call("prompt")

    assert result.provider_used == "ollama"


def test_ollama_500_raises_llm_unavailable():
    """Ollama 500 propagates through as LLMUnavailableError when Anthropic is missing."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock(status=500)):
        with pytest.raises(LLMUnavailableError):
            make_client(anthropic_api_key=None).call("prompt")


# ---------------------------------------------------------------------------
# 4. Bad input / validation
# ---------------------------------------------------------------------------

def test_json_output_non_json_response_raises_llm_json_parse_error():
    """json_output=True with non-JSON response raises LLMJSONParseError."""
    mock_class, _ = make_anthropic_mock(text="This is just plain text, not JSON")
    with patch(ANTHROPIC_PATCH, mock_class):
        with pytest.raises(LLMJSONParseError):
            make_client().call("prompt", json_output=True)


def test_llm_json_parse_error_includes_raw_text():
    """LLMJSONParseError.raw_text contains the original un-parsed response."""
    bad_text = "Sorry, I can't generate JSON for this request."
    mock_class, _ = make_anthropic_mock(text=bad_text)
    with patch(ANTHROPIC_PATCH, mock_class):
        with pytest.raises(LLMJSONParseError) as exc_info:
            make_client().call("prompt", json_output=True)
    assert exc_info.value.raw_text == bad_text


def test_json_parse_error_does_not_fall_back_to_ollama():
    """
    LLMJSONParseError from Anthropic is NOT a provider failure — it should
    NOT trigger a fallback to Ollama. It propagates immediately.
    """
    bad_json = "Not JSON at all"
    mock_class, _ = make_anthropic_mock(text=bad_json)

    with patch(ANTHROPIC_PATCH, mock_class):
        with patch(REQUESTS_POST_PATCH) as mock_ollama:
            with pytest.raises(LLMJSONParseError):
                make_client().call("prompt", json_output=True)

    mock_ollama.assert_not_called()


def test_no_system_prompt_not_sent_to_anthropic():
    """When system_prompt is None, the system kwarg is NOT sent to Anthropic."""
    mock_class, mock_instance = make_anthropic_mock()
    with patch(ANTHROPIC_PATCH, mock_class):
        make_client().call("prompt", system_prompt=None)
    kwargs = mock_instance.messages.create.call_args.kwargs
    assert "system" not in kwargs


def test_no_system_prompt_not_sent_to_ollama():
    """When system_prompt is None, 'system' key is NOT included in Ollama body."""
    with patch(REQUESTS_POST_PATCH, return_value=make_ollama_mock()) as mock_post:
        make_client(anthropic_api_key=None).call("prompt", system_prompt=None)
    sent_body = mock_post.call_args.kwargs["json"]
    assert "system" not in sent_body


# ---------------------------------------------------------------------------
# 5. Idempotency / state
# ---------------------------------------------------------------------------

def test_call_twice_returns_consistent_results():
    """Calling call() twice with the same inputs gives consistent results (no hidden state)."""
    mock_class, _ = make_anthropic_mock(text="Consistent response")
    with patch(ANTHROPIC_PATCH, mock_class):
        client = make_client()
        r1 = client.call("same prompt")
        r2 = client.call("same prompt")

    assert r1.text == r2.text
    assert r1.provider_used == r2.provider_used


def test_client_credentials_unchanged_after_call():
    """LLMClient credentials are not mutated by call()."""
    mock_class, _ = make_anthropic_mock()
    client = make_client()
    with patch(ANTHROPIC_PATCH, mock_class):
        client.call("prompt")
    assert client.anthropic_api_key == ANTHROPIC_KEY
    assert client.ollama_host == OLLAMA_HOST


# ---------------------------------------------------------------------------
# check_ollama_connectivity
# ---------------------------------------------------------------------------

def test_check_ollama_connectivity_returns_true_on_200():
    """check_ollama_connectivity returns True when Ollama responds with 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch(REQUESTS_GET_PATCH, return_value=mock_resp):
        assert make_client().check_ollama_connectivity() is True


def test_check_ollama_connectivity_returns_false_on_non_200():
    """check_ollama_connectivity returns False on non-200 (e.g. 503)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch(REQUESTS_GET_PATCH, return_value=mock_resp):
        assert make_client().check_ollama_connectivity() is False


def test_check_ollama_connectivity_returns_false_on_connection_error():
    """check_ollama_connectivity returns False (never raises) on connection errors."""
    with patch(
        REQUESTS_GET_PATCH,
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        assert make_client().check_ollama_connectivity() is False


def test_check_ollama_connectivity_returns_false_on_timeout():
    """check_ollama_connectivity returns False (never raises) on timeout."""
    with patch(
        REQUESTS_GET_PATCH,
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        assert make_client().check_ollama_connectivity() is False


def test_check_ollama_connectivity_pings_correct_endpoint():
    """check_ollama_connectivity GETs /api/tags on the configured host."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch(REQUESTS_GET_PATCH, return_value=mock_resp) as mock_get:
        make_client(ollama_host="http://myhost:11434").check_ollama_connectivity()
    url = mock_get.call_args.args[0]
    assert url == "http://myhost:11434/api/tags"
