"""
Trello REST API client.

Wraps all Trello board/list/card/label operations needed by consuming agents.
All credentials passed explicitly via constructor — no config file reads.

Rate limiting: exponential backoff on 429 responses (waits 1s, 2s, 4s,
then raises after 3 retries). All API calls logged at DEBUG level.

Auth params (key, token) are sent as query parameters on every request.
"""

import logging
import time

import requests

from agent_shared.trello.models import TrelloCard, TrelloLabel, TrelloList

logger = logging.getLogger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1"
_MAX_RETRIES = 3


class TrelloClient:
    """Trello REST API client. All credentials stored at construction time."""

    def __init__(self, api_key: str, api_token: str, board_id: str) -> None:
        """
        Args:
            api_key: Trello API key.
            api_token: Trello API token.
            board_id: Default board ID for board-scoped operations.
        """
        self.api_key = api_key
        self.api_token = api_token
        self.board_id = board_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth(self) -> dict:
        """Return auth query parameters."""
        return {"key": self.api_key, "token": self.api_token}

    def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        **kwargs,
    ) -> requests.Response:
        """
        Execute an HTTP request with exponential backoff on 429.

        Retries up to _MAX_RETRIES times, waiting 1s, 2s, 4s between attempts.
        Raises requests.HTTPError on non-2xx after exhausting retries.

        Args:
            method: HTTP method ("GET", "POST", "PUT", "DELETE").
            url: Full URL to request.
            params: Additional query parameters (auth is added automatically).
            **kwargs: Passed through to requests.request (e.g. json=, timeout=).

        Returns:
            requests.Response on success.

        Raises:
            requests.HTTPError: On non-2xx response (or 429 after retries).
            requests.RequestException: On network/connection errors.
        """
        all_params = {**self._auth(), **(params or {})}

        for attempt in range(_MAX_RETRIES + 1):
            response = requests.request(
                method, url, params=all_params, timeout=15, **kwargs
            )
            logger.debug(
                "%s %s -> %d (attempt %d)", method, url, response.status_code, attempt + 1
            )

            if response.status_code != 429:
                response.raise_for_status()
                return response

            if attempt < _MAX_RETRIES:
                wait = 2 ** attempt  # 1, 2, 4 seconds
                logger.warning(
                    "Rate limited (429) on %s %s, retrying in %ds (%d/%d)",
                    method, url, wait, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(wait)
            else:
                # Exhausted retries — raise as HTTPError
                response.raise_for_status()

        # Unreachable; satisfies type checkers
        raise RuntimeError("_request loop exited without returning")  # pragma: no cover

    # ------------------------------------------------------------------
    # Card creation (preserved from gmail-to-trello for migration compat)
    # ------------------------------------------------------------------

    def create_card(
        self,
        list_id: str,
        name: str,
        description: str = "",
        position: str = "top",
        label_ids: list[str] | None = None,
    ) -> dict:
        """
        Create a card on the specified list.

        Parameter names for list_id, name, and description are preserved from
        the gmail-to-trello agent's trello_client.create_card for migration
        compatibility. The Trello API field names (idList, desc, pos) differ
        from these Python param names.

        Args:
            list_id: Trello list ID where the card will be created.
            name: Card name (the actionable task).
            description: Card description body.
            position: Position in the list — "top", "bottom", or a float.
            label_ids: Optional list of label IDs to attach.

        Returns:
            Raw Trello API response dict with 'id', 'url', 'shortUrl', etc.

        Raises:
            requests.HTTPError: On non-2xx API response.
        """
        url = f"{TRELLO_API_BASE}/cards"
        body: dict = {
            "idList": list_id,
            "name": name,
            "desc": description,
            "pos": position,
        }
        if label_ids:
            body["idLabels"] = ",".join(label_ids)

        logger.debug("Creating card on list %s: %r", list_id, name)
        response = self._request("POST", url, json=body)
        return response.json()

    # ------------------------------------------------------------------
    # Card reads
    # ------------------------------------------------------------------

    def get_card(self, card_id: str) -> TrelloCard:
        """Get a single card by ID with all fields.

        Args:
            card_id: Trello card ID.

        Returns:
            TrelloCard dataclass populated from API response.
        """
        url = f"{TRELLO_API_BASE}/cards/{card_id}"
        response = self._request("GET", url)
        return _parse_card(response.json())

    def get_list_cards(
        self,
        list_id: str,
        include_closed: bool = False,
    ) -> list[TrelloCard]:
        """Get all cards on a list, parsed into TrelloCard objects.

        Args:
            list_id: Trello list ID.
            include_closed: If True, include archived (closed) cards.

        Returns:
            List of TrelloCard objects.
        """
        url = f"{TRELLO_API_BASE}/lists/{list_id}/cards"
        params = {"filter": "all"} if include_closed else {}
        response = self._request("GET", url, params=params)
        return [_parse_card(c) for c in response.json()]

    def get_multiple_lists_cards(
        self,
        list_ids: list[str],
        include_closed: bool = False,
    ) -> dict[str, list[TrelloCard]]:
        """Get cards across multiple lists in one dict.

        Makes one API call per list — well within Trello rate limits for
        typical list sizes.

        Args:
            list_ids: List of Trello list IDs.
            include_closed: If True, include archived cards.

        Returns:
            Dict mapping each list_id to its list of TrelloCard objects.
        """
        return {
            list_id: self.get_list_cards(list_id, include_closed=include_closed)
            for list_id in list_ids
        }

    # ------------------------------------------------------------------
    # Card mutations
    # ------------------------------------------------------------------

    def move_card(
        self,
        card_id: str,
        target_list_id: str,
        position: str | float = "top",
    ) -> dict:
        """Move a card to a different list and/or position.

        Args:
            card_id: Trello card ID.
            target_list_id: Destination list ID.
            position: Position in the target list ("top", "bottom", or float).

        Returns:
            Raw Trello API response dict.
        """
        url = f"{TRELLO_API_BASE}/cards/{card_id}"
        body = {"idList": target_list_id, "pos": position}
        response = self._request("PUT", url, json=body)
        return response.json()

    def update_card(
        self,
        card_id: str,
        name: str | None = None,
        description: str | None = None,
        position: str | float | None = None,
        label_ids: list[str] | None = None,
        due_date: str | None = None,
        closed: bool | None = None,
    ) -> dict:
        """Update one or more card fields. Only non-None params are sent.

        Args:
            card_id: Trello card ID.
            name: New card name, or None to leave unchanged.
            description: New description, or None to leave unchanged.
            position: New position ("top", "bottom", float), or None.
            label_ids: New label IDs (replaces existing), or None.
            due_date: New due date (ISO 8601 string), or None.
            closed: Set to True to archive, False to unarchive, or None.

        Returns:
            Raw Trello API response dict.
        """
        url = f"{TRELLO_API_BASE}/cards/{card_id}"
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["desc"] = description
        if position is not None:
            body["pos"] = position
        if label_ids is not None:
            body["idLabels"] = ",".join(label_ids)
        if due_date is not None:
            body["due"] = due_date
        if closed is not None:
            body["closed"] = closed

        response = self._request("PUT", url, json=body)
        return response.json()

    def add_comment(self, card_id: str, text: str) -> dict:
        """Add a comment to a card.

        Args:
            card_id: Trello card ID.
            text: Comment text.

        Returns:
            Raw Trello API response dict.
        """
        url = f"{TRELLO_API_BASE}/cards/{card_id}/actions/comments"
        response = self._request("POST", url, json={"text": text})
        return response.json()

    def get_card_actions(
        self,
        card_id: str,
        action_filter: str = "all",
        limit: int = 50,
    ) -> list[dict]:
        """Get card activity/action history.

        Args:
            card_id: Trello card ID.
            action_filter: Trello action filter (e.g. "commentCard", "all").
            limit: Maximum number of actions to return (Trello max: 1000).

        Returns:
            List of raw action dicts from the Trello API.
        """
        url = f"{TRELLO_API_BASE}/cards/{card_id}/actions"
        params = {"filter": action_filter, "limit": limit}
        response = self._request("GET", url, params=params)
        return response.json()

    # ------------------------------------------------------------------
    # Label operations
    # ------------------------------------------------------------------

    def get_board_labels(self) -> list[TrelloLabel]:
        """Get all labels defined on the board.

        Returns:
            List of TrelloLabel objects.
        """
        url = f"{TRELLO_API_BASE}/boards/{self.board_id}/labels"
        response = self._request("GET", url)
        return [
            TrelloLabel(
                id=item["id"],
                name=item.get("name", ""),
                color=item.get("color"),
            )
            for item in response.json()
        ]

    def create_label(self, name: str, color: str = "null") -> TrelloLabel:
        """Create a label on the board.

        Args:
            name: Label name.
            color: Trello color name (e.g. "blue", "red") or "null" for no color.

        Returns:
            TrelloLabel dataclass with the new label's fields.
        """
        url = f"{TRELLO_API_BASE}/boards/{self.board_id}/labels"
        body = {"name": name, "color": color}
        response = self._request("POST", url, json=body)
        data = response.json()
        return TrelloLabel(
            id=data["id"],
            name=data.get("name", ""),
            color=data.get("color"),
        )

    # ------------------------------------------------------------------
    # List operations
    # ------------------------------------------------------------------

    def get_board_lists(self, include_closed: bool = False) -> list[TrelloList]:
        """Get all lists on the board.

        Args:
            include_closed: If True, include archived lists.

        Returns:
            List of TrelloList objects.
        """
        url = f"{TRELLO_API_BASE}/boards/{self.board_id}/lists"
        params = {"filter": "all"} if include_closed else {}
        response = self._request("GET", url, params=params)
        return [
            TrelloList(
                id=item["id"],
                name=item["name"],
                closed=item.get("closed", False),
                position=float(item.get("pos", 0.0)),
            )
            for item in response.json()
        ]

    def validate_list_exists(self, list_id: str) -> bool:
        """Check if a list ID exists on the board. Used at startup.

        Args:
            list_id: The Trello list ID to look for.

        Returns:
            True if the list is found on the board, False otherwise.
        """
        lists = self.get_board_lists()
        found = any(lst.id == list_id for lst in lists)
        logger.debug("validate_list_exists(%s) -> %s", list_id, found)
        return found


# ------------------------------------------------------------------
# Module-level parsing helpers
# ------------------------------------------------------------------

def _parse_card(data: dict) -> TrelloCard:
    """Parse a raw Trello API card dict into a TrelloCard dataclass."""
    labels = [
        TrelloLabel(
            id=lbl["id"],
            name=lbl.get("name", ""),
            color=lbl.get("color"),
        )
        for lbl in data.get("labels", [])
    ]
    return TrelloCard(
        id=data["id"],
        name=data["name"],
        description=data.get("desc", ""),
        list_id=data.get("idList", ""),
        position=float(data.get("pos", 0.0)),
        labels=labels,
        due_date=data.get("due"),
        url=data.get("url", data.get("shortUrl", "")),
        last_activity=data.get("dateLastActivity", ""),
        closed=data.get("closed", False),
    )
