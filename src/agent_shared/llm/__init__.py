"""
agent_shared.llm — LLM inference client and prompt loader.

Re-exports: LLMClient, PromptLoader, LLMResponse, LLMUnavailableError, LLMJSONParseError

Primary provider: Anthropic (Claude Haiku 4.5).
Fallback provider: Ollama (local, model configurable).
If both fail, raises LLMUnavailableError.
"""

from agent_shared.llm.client import LLMClient, LLMJSONParseError, LLMUnavailableError
from agent_shared.llm.prompt_loader import PromptLoader
from agent_shared.models import LLMResponse

__all__ = [
    "LLMClient",
    "PromptLoader",
    "LLMResponse",
    "LLMUnavailableError",
    "LLMJSONParseError",
]
