"""
agent_shared — Reusable library for personal AI agent ecosystem.

Provides: Trello API client, LLM inference (Anthropic + Ollama fallback),
prompt template loading, config loading, logging setup, and SQLite scaffolding.

This is a library. It has no entry point, no main(), and no config files of its own.
All functions accept configuration as parameters from the calling agent.
"""

__version__ = "0.1.0"

# Submodule imports will be added in later phases when source logic is implemented.
# Consumers should import directly from submodules:
#   from agent_shared.trello import TrelloClient
#   from agent_shared.llm import LLMClient
#   from agent_shared.infra import load_config, setup_logging, get_db_connection
