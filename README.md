# agent-shared

A reusable Python library providing Trello API operations, LLM inference (Anthropic primary,
Ollama fallback), prompt template loading, config loading, logging setup, and SQLite scaffolding
for a personal AI agent ecosystem. This is a library, not an application — it has no entry point,
no orchestrator, and no configuration files of its own. Every function accepts configuration as
parameters from the calling agent.

## Installation

From a consuming agent's directory, install as an editable dependency:

```bash
pip install -e ../agent-shared-library
```

## Full Specification

See [CLAUDE.md](./CLAUDE.md) for the complete submodule specs, architecture constraints,
configuration design, and testing strategy.

## Consuming Agents

- **gmail-to-trello** — Existing agent; migrating to use this library for Trello and LLM operations.
- **grooming** — Next agent to be built; will use card reads/mutations and LLM inference.
- **Future agents** — TBD. See Future Scope in CLAUDE.md.
