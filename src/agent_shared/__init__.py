"""
agent_shared — Reusable library for personal AI agent ecosystem.

Provides: Trello API client, LLM inference (Anthropic + Ollama fallback),
prompt template loading, config loading, logging setup, and SQLite scaffolding.

This is a library. It has no entry point, no main(), and no config files of its own.
All functions accept configuration as parameters from the calling agent.
"""

__version__ = "0.1.0"

from agent_shared.llm.client import LLMClient, LLMJSONParseError, LLMUnavailableError
from agent_shared.llm.prompt_loader import PromptLoader
from agent_shared.models import LLMResponse, ProcessingResult
from agent_shared.trello.models import TrelloCard, TrelloLabel, TrelloList

__all__ = [
    "LLMClient",
    "PromptLoader",
    "LLMResponse",
    "LLMUnavailableError",
    "LLMJSONParseError",
    "ProcessingResult",
    "TrelloCard",
    "TrelloLabel",
    "TrelloList",
]
