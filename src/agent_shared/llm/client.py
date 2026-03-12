"""
LLM inference client with automatic Anthropic -> Ollama fallback.

Supports prompt caching (Anthropic), structured JSON output with parse error
handling, and per-call provider tracking via LLMResponse.

All configuration passed explicitly — no config file reads.
"""

# TODO: Implement LLMClient, LLMResponse, LLMUnavailableError, LLMJSONParseError (Phase 4)
