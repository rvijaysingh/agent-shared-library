"""Tests for trello/client.py.

All Trello REST API calls are mocked via unittest.mock.patch on requests.request.
No live HTTP requests are made.

Five categories:
1. Happy path — successful API calls return correct types and values
2. Boundary/edge cases — empty lists, single card, no labels, limit params
3. Graceful degradation — 429 retry logic, 500 error, network timeout
4. Bad input/validation — only non-None params sent in update_card
5. Idempotency/state — client is reusable, same inputs give same results
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from agent_shared.trello.client import TrelloClient
from agent_shared.trello.models import TrelloCard, TrelloLabel, TrelloList

FIXTURES = Path(__file__).parent / "fixtures" / "trello_responses"

API_KEY = "test-api-key"
API_TOKEN = "test-api-token"
BOARD_ID = "board_test_001"
LIST_ID = "list_backlog_001"
CARD_ID = "card_abc123"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def load_fixture(name: str) -> dict | list:
    """Load a JSON fixture file and return parsed data."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_response(status_code: int = 200, body=None) -> MagicMock:
    """Build a mock requests.Response."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code

    if body is None:
        body = {}

    if isinstance(body, (dict, list)):
        mock_resp.json.return_value = body
        mock_resp.text = json.dumps(body)
    else:
        mock_resp.text = str(body)
        mock_resp.json.return_value = {}

    if status_code >= 400:
        http_err = requests.exceptions.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err
    else:
        mock_resp.raise_for_status.return_value = None

    return mock_resp


def make_client() -> TrelloClient:
    return TrelloClient(api_key=API_KEY, api_token=API_TOKEN, board_id=BOARD_ID)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

class TestCreateCard:
    def test_create_card_returns_dict_with_id_and_url(self):
        """create_card returns the raw API response dict."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            result = make_client().create_card(LIST_ID, "Review Q3 deck", "Description")
        assert isinstance(result, dict)
        assert result["id"] == "card_abc123"
        assert "url" in result

    def test_create_card_sends_correct_list_id(self):
        """create_card sends idList in request body."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "Task", "Desc")
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["idList"] == LIST_ID

    def test_create_card_sends_name_and_desc(self):
        """create_card maps name -> name and description -> desc in request."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "My task", "My description")
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["name"] == "My task"
        assert sent_body["desc"] == "My description"

    def test_create_card_defaults_position_to_top(self):
        """create_card sends pos='top' by default."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "Task", "Desc")
        assert mock_req.call_args.kwargs["json"]["pos"] == "top"

    def test_create_card_sends_auth_in_query_params(self):
        """create_card sends api_key and api_token as query params."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "Task", "Desc")
        params = mock_req.call_args.kwargs["params"]
        assert params["key"] == API_KEY
        assert params["token"] == API_TOKEN

    def test_create_card_posts_to_cards_endpoint(self):
        """create_card calls POST /cards."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "Task", "Desc")
        assert mock_req.call_args.args[0] == "POST"
        assert mock_req.call_args.args[1].endswith("/cards")

    def test_create_card_with_label_ids(self):
        """create_card includes label IDs in body when provided."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().create_card(LIST_ID, "Task", "Desc", label_ids=["l1", "l2"])
        sent_body = mock_req.call_args.kwargs["json"]
        assert "l1" in sent_body["idLabels"]
        assert "l2" in sent_body["idLabels"]


class TestGetCard:
    def test_get_card_returns_trello_card(self):
        """get_card returns a TrelloCard dataclass."""
        body = load_fixture("card_get_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            card = make_client().get_card(CARD_ID)
        assert isinstance(card, TrelloCard)
        assert card.id == "card_xyz789"
        assert card.name == "Review architecture doc"

    def test_get_card_parses_labels(self):
        """get_card populates labels as TrelloLabel objects."""
        body = load_fixture("card_get_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            card = make_client().get_card(CARD_ID)
        assert len(card.labels) == 1
        assert isinstance(card.labels[0], TrelloLabel)
        assert card.labels[0].name == "Backend"
        assert card.labels[0].color == "blue"

    def test_get_card_parses_due_date(self):
        """get_card populates due_date from API response."""
        body = load_fixture("card_get_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            card = make_client().get_card(CARD_ID)
        assert card.due_date == "2026-03-15T00:00:00.000Z"


class TestGetListCards:
    def test_get_list_cards_returns_list_of_trello_cards(self):
        """get_list_cards returns a list of TrelloCard objects."""
        body = load_fixture("list_cards_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            cards = make_client().get_list_cards(LIST_ID)
        assert isinstance(cards, list)
        assert all(isinstance(c, TrelloCard) for c in cards)
        assert len(cards) == 2

    def test_get_list_cards_parses_card_fields(self):
        """get_list_cards correctly populates TrelloCard fields from API data."""
        body = load_fixture("list_cards_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            cards = make_client().get_list_cards(LIST_ID)
        assert cards[0].id == "card_abc123"
        assert cards[1].labels[0].name == "Backend"


class TestGetBoardLabels:
    def test_get_board_labels_returns_trello_label_list(self):
        """get_board_labels returns a list of TrelloLabel objects."""
        body = load_fixture("board_labels_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            labels = make_client().get_board_labels()
        assert isinstance(labels, list)
        assert all(isinstance(l, TrelloLabel) for l in labels)
        assert len(labels) == 4

    def test_get_board_labels_parses_color(self):
        """get_board_labels populates color correctly, including None."""
        body = load_fixture("board_labels_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            labels = make_client().get_board_labels()
        assert labels[0].color == "blue"
        assert labels[3].color is None


class TestGetBoardLists:
    def test_get_board_lists_returns_trello_list_objects(self):
        """get_board_lists returns a list of TrelloList objects."""
        body = load_fixture("board_lists_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            lists = make_client().get_board_lists()
        assert isinstance(lists, list)
        assert all(isinstance(l, TrelloList) for l in lists)
        assert len(lists) == 3

    def test_get_board_lists_parses_fields(self):
        """get_board_lists correctly populates all TrelloList fields."""
        body = load_fixture("board_lists_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            lists = make_client().get_board_lists()
        assert lists[0].id == "list_inbox_001"
        assert lists[0].name == "Inbox"
        assert lists[0].position == 16384.0
        assert lists[0].closed is False


class TestMoveCard:
    def test_move_card_sends_correct_params(self):
        """move_card sends idList and pos in request body."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().move_card(CARD_ID, "list_today_001", position="top")
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["idList"] == "list_today_001"
        assert sent_body["pos"] == "top"

    def test_move_card_returns_dict(self):
        """move_card returns the raw API response dict."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            result = make_client().move_card(CARD_ID, "list_today_001")
        assert isinstance(result, dict)


class TestUpdateCard:
    def test_update_card_sends_only_non_none_params(self):
        """update_card omits fields that are None — only sends what was specified."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().update_card(CARD_ID, name="New name")
        sent_body = mock_req.call_args.kwargs["json"]
        assert "name" in sent_body
        assert "desc" not in sent_body
        assert "pos" not in sent_body
        assert "closed" not in sent_body

    def test_update_card_all_fields(self):
        """update_card sends all fields when all are specified."""
        body = load_fixture("card_create_response.json")
        with patch("requests.request", return_value=make_response(200, body)) as mock_req:
            make_client().update_card(
                CARD_ID,
                name="Updated",
                description="New desc",
                position="bottom",
                due_date="2026-04-01",
                closed=False,
            )
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["name"] == "Updated"
        assert sent_body["desc"] == "New desc"
        assert sent_body["pos"] == "bottom"
        assert sent_body["due"] == "2026-04-01"
        assert sent_body["closed"] is False


class TestAddComment:
    def test_add_comment_posts_correct_text(self):
        """add_comment sends text in request body to correct endpoint."""
        comment_body = {"id": "action_001", "type": "commentCard"}
        with patch("requests.request", return_value=make_response(200, comment_body)) as mock_req:
            result = make_client().add_comment(CARD_ID, "Please review ASAP")
        sent_body = mock_req.call_args.kwargs["json"]
        assert sent_body["text"] == "Please review ASAP"
        url = mock_req.call_args.args[1]
        assert f"/cards/{CARD_ID}/actions/comments" in url


class TestGetMultipleListsCards:
    def test_get_multiple_lists_cards_returns_dict_of_lists(self):
        """get_multiple_lists_cards returns a dict mapping list_id to TrelloCard list."""
        body = load_fixture("list_cards_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            result = make_client().get_multiple_lists_cards(["list_a", "list_b"])
        assert isinstance(result, dict)
        assert "list_a" in result
        assert "list_b" in result
        assert all(isinstance(c, TrelloCard) for c in result["list_a"])


class TestValidateListExists:
    def test_validate_list_exists_returns_true_for_known_id(self):
        """validate_list_exists returns True when the list is found on the board."""
        body = load_fixture("board_lists_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            result = make_client().validate_list_exists("list_backlog_001")
        assert result is True

    def test_validate_list_exists_returns_false_for_unknown_id(self):
        """validate_list_exists returns False when list is not on the board."""
        body = load_fixture("board_lists_response.json")
        with patch("requests.request", return_value=make_response(200, body)):
            result = make_client().validate_list_exists("list_nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_get_list_cards_empty_list():
    """get_list_cards returns an empty list when the API returns []."""
    with patch("requests.request", return_value=make_response(200, [])):
        cards = make_client().get_list_cards(LIST_ID)
    assert cards == []


def test_get_list_cards_single_card():
    """get_list_cards handles a single-card response."""
    body = [load_fixture("list_cards_response.json")[0]]  # just the first card
    with patch("requests.request", return_value=make_response(200, body)):
        cards = make_client().get_list_cards(LIST_ID)
    assert len(cards) == 1
    assert isinstance(cards[0], TrelloCard)


def test_get_card_with_no_labels():
    """get_card returns TrelloCard with empty labels when API returns no labels."""
    body = load_fixture("card_create_response.json")  # has labels: []
    with patch("requests.request", return_value=make_response(200, body)):
        card = make_client().get_card(CARD_ID)
    assert card.labels == []


def test_get_card_with_no_due_date():
    """get_card sets due_date to None when API returns null."""
    body = load_fixture("card_create_response.json")  # has due: null
    with patch("requests.request", return_value=make_response(200, body)):
        card = make_client().get_card(CARD_ID)
    assert card.due_date is None


def test_get_card_actions_with_limit():
    """get_card_actions sends limit as query param."""
    body = load_fixture("card_actions_response.json")
    with patch("requests.request", return_value=make_response(200, body)) as mock_req:
        actions = make_client().get_card_actions(CARD_ID, limit=1)
    params = mock_req.call_args.kwargs["params"]
    assert params["limit"] == 1
    assert isinstance(actions, list)


def test_update_card_single_field_only():
    """update_card with only name specified sends only name in body."""
    body = load_fixture("card_create_response.json")
    with patch("requests.request", return_value=make_response(200, body)) as mock_req:
        make_client().update_card(CARD_ID, name="Only name changed")
    sent_body = mock_req.call_args.kwargs["json"]
    assert list(sent_body.keys()) == ["name"]


# ---------------------------------------------------------------------------
# 3. Graceful degradation — retry and error handling
# ---------------------------------------------------------------------------

def test_rate_limit_retries_then_succeeds():
    """
    429 response triggers exponential backoff; success on the second attempt.
    Verifies retry logic (429 -> retry -> 200).
    """
    rate_limit_resp = make_response(429, {"error": "rate limit"})
    success_resp = make_response(200, load_fixture("list_cards_response.json"))

    with patch("requests.request", side_effect=[rate_limit_resp, success_resp]):
        with patch("agent_shared.trello.client.time.sleep") as mock_sleep:
            cards = make_client().get_list_cards(LIST_ID)

    # Should have slept once (1 second for the first retry)
    mock_sleep.assert_called_once_with(1)
    assert len(cards) == 2


def test_rate_limit_retries_multiple_then_succeeds():
    """429 x2, then success — verifies second retry uses 2s backoff."""
    rl = make_response(429, {"error": "rate limit"})
    ok = make_response(200, load_fixture("list_cards_response.json"))

    with patch("requests.request", side_effect=[rl, rl, ok]):
        with patch("agent_shared.trello.client.time.sleep") as mock_sleep:
            cards = make_client().get_list_cards(LIST_ID)

    assert mock_sleep.call_args_list == [call(1), call(2)]
    assert len(cards) == 2


def test_rate_limit_exhausts_retries_and_raises():
    """
    Three consecutive 429 responses exhaust all retries and raise HTTPError.
    Verifies that after 3 retries (waits 1s, 2s, 4s), the error propagates.
    """
    rl = make_response(429, {"error": "rate limit"})

    with patch("requests.request", side_effect=[rl, rl, rl, rl]):
        with patch("agent_shared.trello.client.time.sleep") as mock_sleep:
            with pytest.raises(requests.exceptions.HTTPError):
                make_client().get_list_cards(LIST_ID)

    # Should have slept 3 times: 1s, 2s, 4s
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


def test_server_error_raises_http_error():
    """500 response raises requests.HTTPError immediately (no retry)."""
    with patch("requests.request", return_value=make_response(500, "internal server error")):
        with pytest.raises(requests.exceptions.HTTPError):
            make_client().get_list_cards(LIST_ID)


def test_network_timeout_raises():
    """Connection timeout raises requests.Timeout."""
    with patch(
        "requests.request",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            make_client().get_list_cards(LIST_ID)


def test_connection_error_raises():
    """Network connection error propagates as requests.ConnectionError."""
    with patch(
        "requests.request",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            make_client().create_card(LIST_ID, "Task", "Desc")


def test_unauthorized_raises_http_error():
    """401 unauthorized raises HTTPError without retry."""
    with patch("requests.request", return_value=make_response(401, "unauthorized")):
        with pytest.raises(requests.exceptions.HTTPError):
            make_client().get_board_labels()


# ---------------------------------------------------------------------------
# 4. Bad input / parameter validation
# ---------------------------------------------------------------------------

def test_update_card_no_fields_sends_empty_body():
    """update_card with all None args sends an empty body (no fields to update)."""
    body = load_fixture("card_create_response.json")
    with patch("requests.request", return_value=make_response(200, body)) as mock_req:
        make_client().update_card(CARD_ID)
    sent_body = mock_req.call_args.kwargs["json"]
    assert sent_body == {}


def test_create_card_empty_description_is_valid():
    """create_card with empty description sends desc='' (not an error)."""
    body = load_fixture("card_create_response.json")
    with patch("requests.request", return_value=make_response(200, body)) as mock_req:
        make_client().create_card(LIST_ID, "Task", "")
    assert mock_req.call_args.kwargs["json"]["desc"] == ""


def test_get_list_cards_include_closed_sends_filter_all():
    """get_list_cards with include_closed=True sends filter=all query param."""
    with patch("requests.request", return_value=make_response(200, [])) as mock_req:
        make_client().get_list_cards(LIST_ID, include_closed=True)
    params = mock_req.call_args.kwargs["params"]
    assert params.get("filter") == "all"


def test_get_list_cards_exclude_closed_sends_no_filter():
    """get_list_cards with include_closed=False (default) sends no filter param."""
    with patch("requests.request", return_value=make_response(200, [])) as mock_req:
        make_client().get_list_cards(LIST_ID, include_closed=False)
    params = mock_req.call_args.kwargs["params"]
    assert "filter" not in params


# ---------------------------------------------------------------------------
# 5. Idempotency / state — client reusability
# ---------------------------------------------------------------------------

def test_client_is_reusable_across_calls():
    """TrelloClient instance can make multiple calls without state corruption."""
    list_body = load_fixture("list_cards_response.json")
    label_body = load_fixture("board_labels_response.json")

    client = make_client()
    with patch("requests.request", return_value=make_response(200, list_body)):
        cards = client.get_list_cards(LIST_ID)

    with patch("requests.request", return_value=make_response(200, label_body)):
        labels = client.get_board_labels()

    assert len(cards) == 2
    assert len(labels) == 4
    assert client.api_key == API_KEY  # credentials unchanged


def test_get_list_cards_called_twice_returns_same_results():
    """Calling get_list_cards twice with the same input returns identical results."""
    body = load_fixture("list_cards_response.json")
    client = make_client()

    with patch("requests.request", return_value=make_response(200, body)):
        result1 = client.get_list_cards(LIST_ID)

    with patch("requests.request", return_value=make_response(200, body)):
        result2 = client.get_list_cards(LIST_ID)

    assert result1 == result2


def test_get_multiple_lists_cards_makes_one_call_per_list():
    """get_multiple_lists_cards makes exactly one API call per list_id."""
    body = load_fixture("list_cards_response.json")
    list_ids = ["list_a", "list_b", "list_c"]

    with patch("requests.request", return_value=make_response(200, body)) as mock_req:
        result = make_client().get_multiple_lists_cards(list_ids)

    assert mock_req.call_count == 3
    assert set(result.keys()) == set(list_ids)
