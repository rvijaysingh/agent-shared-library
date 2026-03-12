"""
Trello data model dataclasses.

TrelloLabel, TrelloCard, TrelloList — plain dataclasses representing
Trello API objects. No business logic, no API calls.
"""

from dataclasses import dataclass, field


@dataclass
class TrelloLabel:
    """A label attached to a Trello card or defined on a board."""

    id: str
    name: str
    color: str | None = None


@dataclass
class TrelloCard:
    """A Trello card with all fields returned by the API."""

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
    """A Trello list (column) on a board."""

    id: str
    name: str
    closed: bool = False
    position: float = 0.0
