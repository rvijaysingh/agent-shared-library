"""
agent_shared.trello — Trello REST API client and data models.

Re-exports: TrelloClient, TrelloCard, TrelloList, TrelloLabel

All Trello credentials (api_key, api_token, board_id) are passed
as constructor parameters to TrelloClient. No config file reads here.
"""

from agent_shared.trello.client import TrelloClient
from agent_shared.trello.models import TrelloCard, TrelloLabel, TrelloList

__all__ = [
    "TrelloClient",
    "TrelloCard",
    "TrelloLabel",
    "TrelloList",
]
