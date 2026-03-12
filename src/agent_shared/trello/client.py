"""
Trello REST API client.

Wraps all Trello board/list/card/label operations needed by consuming agents.
All credentials passed explicitly via constructor — no config file reads.

Implements exponential backoff on 429 responses (max 3 retries).
Logs all API calls at DEBUG level for rate-limit diagnostics.
"""

# TODO: Implement TrelloClient (Phase 3)
