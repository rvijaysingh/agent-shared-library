"""Tests for top-level models.py (LLMResponse, ProcessingResult).

Verifies construction, defaults, auto-timestamp, and mutable field independence.
"""

import re
import pytest

from agent_shared.models import LLMResponse, ProcessingResult


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------

def test_llm_response_required_fields():
    """LLMResponse requires text and provider_used; all others default."""
    resp = LLMResponse(text="Hello world", provider_used="anthropic")
    assert resp.text == "Hello world"
    assert resp.provider_used == "anthropic"
    assert resp.tokens_in == 0
    assert resp.tokens_out == 0
    assert resp.cached is False
    assert resp.model == ""


def test_llm_response_all_fields():
    """LLMResponse stores all explicitly provided fields."""
    resp = LLMResponse(
        text='{"action": "create"}',
        provider_used="ollama",
        tokens_in=150,
        tokens_out=42,
        cached=True,
        model="qwen3:8b",
    )
    assert resp.tokens_in == 150
    assert resp.tokens_out == 42
    assert resp.cached is True
    assert resp.model == "qwen3:8b"


def test_llm_response_cached_defaults_false():
    """LLMResponse.cached defaults to False."""
    resp = LLMResponse(text="ok", provider_used="anthropic")
    assert resp.cached is False


def test_llm_response_equality():
    """Two LLMResponse instances with same fields are equal."""
    a = LLMResponse(text="hi", provider_used="anthropic", tokens_in=10)
    b = LLMResponse(text="hi", provider_used="anthropic", tokens_in=10)
    assert a == b


# ---------------------------------------------------------------------------
# ProcessingResult
# ---------------------------------------------------------------------------

def test_processing_result_auto_timestamp_when_empty():
    """ProcessingResult auto-populates timestamp with ISO 8601 when left empty."""
    result = ProcessingResult(success=True, item_id="msg_001", action="created")
    assert result.timestamp != ""
    # Must be parseable as ISO 8601
    from datetime import datetime
    parsed = datetime.fromisoformat(result.timestamp)
    assert parsed is not None


def test_processing_result_explicit_timestamp_preserved():
    """ProcessingResult preserves a non-empty timestamp without modification."""
    ts = "2026-03-12T10:00:00+00:00"
    result = ProcessingResult(success=True, item_id="msg_001", action="created", timestamp=ts)
    assert result.timestamp == ts


def test_processing_result_required_fields():
    """ProcessingResult requires success, item_id, action."""
    result = ProcessingResult(success=False, item_id="email_xyz", action="skipped")
    assert result.success is False
    assert result.item_id == "email_xyz"
    assert result.action == "skipped"
    assert result.details == {}
    assert result.error_message is None


def test_processing_result_all_fields():
    """ProcessingResult stores all explicitly provided fields."""
    result = ProcessingResult(
        success=True,
        item_id="card_abc",
        action="moved",
        details={"from_list": "Inbox", "to_list": "Today"},
        error_message=None,
        timestamp="2026-03-12T09:00:00+00:00",
    )
    assert result.details["from_list"] == "Inbox"
    assert result.error_message is None


def test_processing_result_default_details_are_independent():
    """
    Two separately constructed ProcessingResults have independent details dicts.
    Mutating one does not affect the other (default_factory=dict).
    """
    a = ProcessingResult(success=True, item_id="a", action="created")
    b = ProcessingResult(success=True, item_id="b", action="created")

    a.details["key"] = "value"

    assert "key" in a.details
    assert "key" not in b.details


def test_processing_result_error_message_stored():
    """ProcessingResult stores error_message when provided."""
    result = ProcessingResult(
        success=False,
        item_id="msg_fail",
        action="failed",
        error_message="Trello API returned 500",
    )
    assert result.error_message == "Trello API returned 500"


def test_processing_result_timestamp_is_utc_iso8601():
    """Auto-generated timestamp is in UTC ISO 8601 format with timezone info."""
    result = ProcessingResult(success=True, item_id="x", action="created")
    # Should contain timezone offset (+00:00 or Z)
    assert "+" in result.timestamp or result.timestamp.endswith("Z")
