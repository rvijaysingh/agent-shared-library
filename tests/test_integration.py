"""
Integration tests — simulated consumer usage patterns.

Exercises the full agent_shared library from the perspective of two consuming agents:
- TestGmailToTrelloUsagePattern: config → TrelloClient card creation → LLM call → SQLite write
- TestGroomingAgentUsagePattern: multi-list card reads → LLM JSON scoring → card mutation

All external dependencies (Trello API, Anthropic SDK, Ollama HTTP) are mocked.
No live network calls are made.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from agent_shared.infra import (
    db_connection,
    ensure_table,
    load_config,
)
from agent_shared.llm import LLMClient, PromptLoader
from agent_shared.models import LLMResponse, ProcessingResult
from agent_shared.trello import TrelloClient
from agent_shared.trello.models import TrelloCard

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TRELLO_FIXTURES = FIXTURES_DIR / "trello_responses"

ANTHROPIC_PATCH = "agent_shared.llm.client.anthropic.Anthropic"
REQUESTS_POST_PATCH = "agent_shared.llm.client.requests.post"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_trello_response(status_code: int = 200, body=None) -> MagicMock:
    """Build a mock requests.Response for Trello API calls."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    if body is None:
        body = {}
    mock_resp.json.return_value = body
    mock_resp.text = json.dumps(body)
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


def make_anthropic_mock(text: str, tokens_in: int = 100, tokens_out: int = 20) -> MagicMock:
    """Build a mock anthropic.Anthropic class that returns the given text."""
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
    mock_response.usage.cache_read_input_tokens = 0

    mock_instance.messages.create.return_value = mock_response
    return mock_class


def make_ollama_response(text: str) -> MagicMock:
    """Build a mock requests.Response for Ollama /api/generate."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"model": "qwen3:8b", "response": text, "done": True}
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def load_trello_fixture(name: str):
    """Load a JSON fixture from the trello_responses directory."""
    return json.loads((TRELLO_FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Class 1: Gmail-to-Trello usage pattern
# ---------------------------------------------------------------------------

class TestGmailToTrelloUsagePattern:
    """
    Simulates the gmail-to-trello agent's usage of agent-shared.
    Mirrors the pattern: load config -> create TrelloClient -> create card.
    """

    def test_config_load_and_trello_card_creation(self):
        """
        Load config from sample_env.json, create TrelloClient, mock create_card,
        verify result dict has 'id' and 'url' keys (as the orchestrator expects).
        """
        config = load_config(config_path=str(FIXTURES_DIR / "sample_env.json"))

        client = TrelloClient(
            api_key=config["trello_api_key"],
            api_token=config["trello_api_token"],
            board_id=config["trello_board_id"],
        )

        card_body = load_trello_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_trello_response(200, card_body)):
            result = client.create_card(
                list_id="list_backlog_001",
                name="Review Q3 board deck",
                description="See email from Alice",
            )

        # The gmail-to-trello agent extracts id and url from the dict result
        assert isinstance(result, dict)
        assert "id" in result
        assert "url" in result
        assert result["id"] == "card_abc123"

    def test_config_load_and_llm_call_with_fallback(self):
        """
        Load config, extract the gmail-to-trello Anthropic key, create LLMClient,
        create PromptLoader with fixtures dir as prompts_dir.
        Mock Anthropic to fail, mock Ollama to succeed.
        Verify provider_used="ollama" (fallback was used).
        """
        config = load_config(config_path=str(FIXTURES_DIR / "sample_env.json"))

        anthropic_key = config["anthropic_api_keys"]["gmail-to-trello"]
        client = LLMClient(
            anthropic_api_key=anthropic_key,
            ollama_host="http://localhost:11434",
            ollama_model="qwen3:8b",
        )

        loader = PromptLoader(prompts_dir=str(FIXTURES_DIR))

        # Load and render the test prompt template
        prompt = loader.load(
            "test_prompt.md",
            {"subject": "Q3 Board Review", "body": "Please review by Friday."},
        )
        assert "Q3 Board Review" in prompt
        assert "Please review by Friday." in prompt

        # Anthropic fails, Ollama succeeds
        failing_anthropic = MagicMock()
        failing_anthropic.return_value.messages.create.side_effect = Exception(
            "Anthropic connection refused"
        )

        with patch(ANTHROPIC_PATCH, failing_anthropic):
            with patch(REQUESTS_POST_PATCH, return_value=make_ollama_response("Review Q3 deck")):
                response = client.call(prompt, max_tokens=50)

        assert isinstance(response, LLMResponse)
        assert response.provider_used == "ollama"
        assert response.text == "Review Q3 deck"

    def test_full_pipeline_simulation(self, tmp_path):
        """
        Simulate the full gmail-to-trello pipeline:
        1. Load config from sample_env.json
        2. Call LLM to generate a card name (mocked Anthropic success)
        3. Create a Trello card (mocked)
        4. Insert a processed-email record into SQLite
        5. Query and verify the record
        """
        config = load_config(config_path=str(FIXTURES_DIR / "sample_env.json"))

        # Step 1: LLM generates card name
        anthropic_key = config["anthropic_api_keys"]["gmail-to-trello"]
        llm_client = LLMClient(anthropic_api_key=anthropic_key)

        card_name_text = "Review Q3 board deck"
        mock_anthropic = make_anthropic_mock(text=card_name_text)

        with patch(ANTHROPIC_PATCH, mock_anthropic):
            llm_response = llm_client.call(
                "Generate a card name for: Q3 Board Review",
                max_tokens=50,
            )

        assert llm_response.text == card_name_text
        assert llm_response.provider_used == "anthropic"

        # Step 2: Create Trello card
        trello_client = TrelloClient(
            api_key=config["trello_api_key"],
            api_token=config["trello_api_token"],
            board_id=config["trello_board_id"],
        )
        card_body = load_trello_fixture("card_create_response.json")

        with patch("requests.request", return_value=make_trello_response(200, card_body)):
            card_result = trello_client.create_card(
                list_id="list_backlog_001",
                name=llm_response.text,
                description="Gmail message ID: msg_001",
            )

        card_id = card_result["id"]
        card_url = card_result["url"]

        # Step 3: Insert record into SQLite (using raw SQL, as the agent would)
        db_path = str(tmp_path / "agent.db")
        create_sql = """
            CREATE TABLE IF NOT EXISTS processed_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_id TEXT NOT NULL UNIQUE,
                card_id TEXT NOT NULL,
                card_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """

        with db_connection(db_path) as conn:
            ensure_table(conn, create_sql)
            conn.execute(
                "INSERT INTO processed_emails (gmail_id, card_id, card_url, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("msg_001", card_id, card_url, "2026-03-12T10:00:00+00:00"),
            )

        # Step 4: Verify the record was committed
        with db_connection(db_path) as conn:
            row = conn.execute(
                "SELECT gmail_id, card_id, card_url FROM processed_emails WHERE gmail_id=?",
                ("msg_001",),
            ).fetchone()

        assert row is not None
        assert row["gmail_id"] == "msg_001"
        assert row["card_id"] == card_id
        assert row["card_url"] == card_url

        # Also construct a ProcessingResult to verify the model works end-to-end
        result = ProcessingResult(
            success=True,
            item_id="msg_001",
            action="created",
            details={"card_id": card_id, "card_url": card_url},
        )
        assert result.success is True
        assert result.timestamp != ""


# ---------------------------------------------------------------------------
# Class 2: Grooming agent usage pattern
# ---------------------------------------------------------------------------

class TestGroomingAgentUsagePattern:
    """
    Simulates the grooming agent's usage of agent-shared.
    Focuses on card reads, LLM JSON scoring, and card mutations.
    """

    def test_read_cards_across_lists(self):
        """
        Create TrelloClient, mock requests.request to return list_cards_response.json,
        call get_multiple_lists_cards with 3 list IDs.
        Verify the result dict has 3 keys, each mapping to a list of TrelloCard objects.
        """
        client = TrelloClient(
            api_key="test-key",
            api_token="test-token",
            board_id="board_test",
        )

        list_body = load_trello_fixture("list_cards_response.json")
        list_ids = ["list_inbox_001", "list_backlog_001", "list_today_001"]

        with patch("requests.request", return_value=make_trello_response(200, list_body)):
            result = client.get_multiple_lists_cards(list_ids)

        assert isinstance(result, dict)
        assert set(result.keys()) == set(list_ids)

        # Each list should have TrelloCard objects
        for list_id in list_ids:
            cards = result[list_id]
            assert isinstance(cards, list)
            assert len(cards) == 2  # fixture has 2 cards
            assert all(isinstance(c, TrelloCard) for c in cards)

        # Verify card data from fixture is parsed correctly
        first_card = result["list_inbox_001"][0]
        assert first_card.id == "card_abc123"
        assert first_card.name == "Review Q3 board deck"

    def test_llm_scoring_with_json_output(self):
        """
        Create LLMClient with api_key, mock Anthropic to return a JSON string.
        Call with json_output=True and cache_system_prompt=True.
        Verify the response text is parseable JSON with expected structure.
        """
        client = LLMClient(
            anthropic_api_key="sk-ant-test-grooming-key",
            ollama_model="qwen3:8b",
        )

        score_json = '{"score": 8, "reason": "High priority: due soon with no owner"}'
        mock_anthropic = make_anthropic_mock(text=score_json)

        with patch(ANTHROPIC_PATCH, mock_anthropic):
            response = client.call(
                prompt="Score this card: Review Q3 board deck",
                system_prompt="You are a backlog grooming assistant. Return JSON only.",
                max_tokens=200,
                json_output=True,
                cache_system_prompt=True,
            )

        assert isinstance(response, LLMResponse)
        assert response.provider_used == "anthropic"

        # The text must be parseable JSON
        parsed = json.loads(response.text)
        assert "score" in parsed
        assert parsed["score"] == 8
        assert "reason" in parsed

    def test_card_move_and_label_update(self):
        """
        Create TrelloClient, mock move_card and update_card.
        Verify that the correct API calls are made with the expected parameters.
        """
        client = TrelloClient(
            api_key="test-key",
            api_token="test-token",
            board_id="board_test",
        )

        card_body = load_trello_fixture("card_create_response.json")

        with patch("requests.request", return_value=make_trello_response(200, card_body)) as mock_req:
            move_result = client.move_card(
                card_id="card_abc123",
                target_list_id="list_today_001",
                position="top",
            )

        assert isinstance(move_result, dict)
        # Verify PUT /cards/{id} called with correct body
        call_args = mock_req.call_args
        assert call_args.args[0] == "PUT"
        assert "card_abc123" in call_args.args[1]
        sent_body = call_args.kwargs["json"]
        assert sent_body["idList"] == "list_today_001"
        assert sent_body["pos"] == "top"

        # Update card labels
        with patch("requests.request", return_value=make_trello_response(200, card_body)) as mock_req2:
            update_result = client.update_card(
                card_id="card_abc123",
                label_ids=["label_urgent_001", "label_backend_002"],
            )

        assert isinstance(update_result, dict)
        update_body = mock_req2.call_args.kwargs["json"]
        assert "label_urgent_001" in update_body["idLabels"]
        assert "label_backend_002" in update_body["idLabels"]

    def test_card_comment_and_activity(self):
        """
        Create TrelloClient, mock add_comment and get_card_actions.
        Verify comment text is sent correctly and actions list is returned.
        """
        client = TrelloClient(
            api_key="test-key",
            api_token="test-token",
            board_id="board_test",
        )

        comment_body = {
            "id": "action_comment_001",
            "type": "commentCard",
            "data": {"text": "Grooming: scored 8/10, moving to Today"},
        }

        with patch("requests.request", return_value=make_trello_response(200, comment_body)) as mock_req:
            comment_result = client.add_comment(
                card_id="card_abc123",
                text="Grooming: scored 8/10, moving to Today",
            )

        assert isinstance(comment_result, dict)
        # Verify comment text was sent in body
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["text"] == "Grooming: scored 8/10, moving to Today"
        # Verify endpoint
        url = mock_req.call_args.args[1]
        assert "/cards/card_abc123/actions/comments" in url

        # Get card action history
        actions_body = [
            {"id": "action_001", "type": "commentCard", "data": {"text": "Groomed"}},
            {"id": "action_002", "type": "updateCard", "data": {"listAfter": {"name": "Today"}}},
        ]

        with patch("requests.request", return_value=make_trello_response(200, actions_body)) as mock_req2:
            actions = client.get_card_actions(
                card_id="card_abc123",
                action_filter="commentCard",
                limit=10,
            )

        assert isinstance(actions, list)
        assert len(actions) == 2
        assert actions[0]["id"] == "action_001"
        # Verify query params were sent
        sent_params = mock_req2.call_args.kwargs["params"]
        assert sent_params["filter"] == "commentCard"
        assert sent_params["limit"] == 10
