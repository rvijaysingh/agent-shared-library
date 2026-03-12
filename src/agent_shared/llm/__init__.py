"""
agent_shared.llm — LLM inference client and prompt loader.

Re-exports: LLMClient, PromptLoader, LLMResponse

Primary provider: Anthropic (Claude Haiku 4.5).
Fallback provider: Ollama (local, model configurable).
If both fail, raises LLMUnavailableError.
"""

# Re-exports will be added when source logic is implemented.
# from agent_shared.llm.client import LLMClient, LLMResponse, LLMUnavailableError, LLMJSONParseError
# from agent_shared.llm.prompt_loader import PromptLoader
