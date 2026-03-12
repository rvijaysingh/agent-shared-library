"""Tests for trello/models.py.

Verifies dataclass construction, defaults, equality, and independence of
mutable default_factory fields.
"""

import pytest

from agent_shared.trello.models import TrelloCard, TrelloLabel, TrelloList


# ---------------------------------------------------------------------------
# TrelloLabel
# ---------------------------------------------------------------------------

def test_trello_label_required_fields():
    """TrelloLabel requires id and name."""
    label = TrelloLabel(id="label_001", name="Backend")
    assert label.id == "label_001"
    assert label.name == "Backend"
    assert label.color is None


def test_trello_label_with_color():
    """TrelloLabel stores color when provided."""
    label = TrelloLabel(id="label_002", name="Urgent", color="red")
    assert label.color == "red"


def test_trello_label_color_none_is_default():
    """TrelloLabel color defaults to None."""
    label = TrelloLabel(id="x", name="y")
    assert label.color is None


def test_trello_label_equality():
    """Two TrelloLabel instances with the same fields are equal."""
    a = TrelloLabel(id="l1", name="Tag", color="blue")
    b = TrelloLabel(id="l1", name="Tag", color="blue")
    assert a == b


# ---------------------------------------------------------------------------
# TrelloCard
# ---------------------------------------------------------------------------

def test_trello_card_required_fields_only():
    """TrelloCard can be constructed with only id and name; all others default."""
    card = TrelloCard(id="card_001", name="Do the thing")
    assert card.id == "card_001"
    assert card.name == "Do the thing"
    assert card.description == ""
    assert card.list_id == ""
    assert card.position == 0.0
    assert card.labels == []
    assert card.due_date is None
    assert card.url == ""
    assert card.last_activity == ""
    assert card.closed is False


def test_trello_card_all_fields():
    """TrelloCard stores all explicitly provided fields correctly."""
    label = TrelloLabel(id="l1", name="Backend", color="blue")
    card = TrelloCard(
        id="card_xyz",
        name="Review PR",
        description="Please review by Friday",
        list_id="list_today",
        position=65536.0,
        labels=[label],
        due_date="2026-03-15T00:00:00.000Z",
        url="https://trello.com/c/xyz",
        last_activity="2026-03-12T10:00:00.000Z",
        closed=False,
    )
    assert card.description == "Please review by Friday"
    assert card.list_id == "list_today"
    assert card.position == 65536.0
    assert len(card.labels) == 1
    assert card.labels[0].name == "Backend"
    assert card.due_date == "2026-03-15T00:00:00.000Z"
    assert card.url == "https://trello.com/c/xyz"
    assert card.closed is False


def test_trello_card_with_no_labels():
    """TrelloCard with empty labels list is valid."""
    card = TrelloCard(id="c1", name="Task", labels=[])
    assert card.labels == []


def test_trello_card_with_multiple_labels():
    """TrelloCard holds multiple TrelloLabel instances."""
    labels = [
        TrelloLabel(id="l1", name="Backend", color="blue"),
        TrelloLabel(id="l2", name="Urgent", color="red"),
    ]
    card = TrelloCard(id="c1", name="Fix bug", labels=labels)
    assert len(card.labels) == 2
    assert card.labels[1].name == "Urgent"


def test_trello_card_closed_flag():
    """TrelloCard closed field is stored correctly."""
    card = TrelloCard(id="c1", name="Old task", closed=True)
    assert card.closed is True


def test_trello_card_default_labels_are_independent():
    """
    Two separately constructed TrelloCards have independent labels lists.
    Mutating one card's labels list does not affect the other.
    (Verifies that default_factory=list creates a new list per instance.)
    """
    card_a = TrelloCard(id="a", name="Card A")
    card_b = TrelloCard(id="b", name="Card B")

    card_a.labels.append(TrelloLabel(id="l1", name="Tag", color="blue"))

    assert len(card_a.labels) == 1
    assert len(card_b.labels) == 0


def test_trello_card_equality():
    """Two TrelloCard instances with same fields are equal."""
    card_a = TrelloCard(id="c1", name="Task", description="desc")
    card_b = TrelloCard(id="c1", name="Task", description="desc")
    assert card_a == card_b


# ---------------------------------------------------------------------------
# TrelloList
# ---------------------------------------------------------------------------

def test_trello_list_required_fields_only():
    """TrelloList can be constructed with only id and name."""
    lst = TrelloList(id="list_001", name="Backlog")
    assert lst.id == "list_001"
    assert lst.name == "Backlog"
    assert lst.closed is False
    assert lst.position == 0.0


def test_trello_list_all_fields():
    """TrelloList stores all explicitly provided fields."""
    lst = TrelloList(id="list_001", name="Done", closed=True, position=98304.0)
    assert lst.closed is True
    assert lst.position == 98304.0


def test_trello_list_equality():
    """Two TrelloList instances with same fields are equal."""
    a = TrelloList(id="l1", name="Today", closed=False, position=16384.0)
    b = TrelloList(id="l1", name="Today", closed=False, position=16384.0)
    assert a == b
