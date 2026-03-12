"""
Top-level shared data models for agent_shared.

Contains ProcessingResult and LLMResponse — generic dataclasses used
across all consuming agents and submodules.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LLMResponse:
    """Result from a single LLM inference call."""

    text: str
    provider_used: str          # "anthropic" or "ollama"
    tokens_in: int = 0
    tokens_out: int = 0
    cached: bool = False        # True if Anthropic prompt cache hit
    model: str = ""


@dataclass
class ProcessingResult:
    """Generic outcome record for agent processing operations."""

    success: bool
    item_id: str                # Generic ID of the processed item (e.g. gmail_message_id)
    action: str                 # What was done: "created", "moved", "skipped", etc.
    details: dict = field(default_factory=dict)
    error_message: str | None = None
    timestamp: str = ""         # ISO 8601 UTC; auto-set in __post_init__ if empty

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
