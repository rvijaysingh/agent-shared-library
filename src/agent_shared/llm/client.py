"""
LLM inference client with automatic Anthropic -> Ollama fallback.

Supports prompt caching (Anthropic), structured JSON output with parse error
handling, and per-call provider tracking via LLMResponse.

All configuration passed explicitly — no config file reads.

Fallback chain: Anthropic (if api_key configured) -> Ollama -> LLMUnavailableError.

Key LESSONS applied:
- Anthropic token fields are input_tokens / output_tokens (not prompt_tokens).
- Anthropic prompt caching uses cache_control={"type": "ephemeral"} on the system block;
  cache hits are confirmed via response.usage.cache_read_input_tokens > 0.
- Ollama /api/generate requires stream=false (Python False) to get a single response.
"""

import json
import logging
import re

import anthropic
import requests

from agent_shared.models import LLMResponse

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?", re.IGNORECASE)


class LLMUnavailableError(Exception):
    """Raised when all configured LLM providers fail."""
    pass


class LLMJSONParseError(Exception):
    """Raised when json_output=True but the LLM response is not valid JSON."""

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class LLMClient:
    """LLM inference client with Anthropic primary and Ollama fallback."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "qwen3:8b",
        anthropic_model: str = "claude-haiku-4-5-20241022",
    ) -> None:
        """
        Args:
            anthropic_api_key: Anthropic API key. If None or empty string, Anthropic
                is skipped and Ollama is tried first.
            ollama_host: Base URL of the local Ollama service.
            ollama_model: Model name to use with Ollama (e.g. "qwen3:8b").
            anthropic_model: Anthropic model ID (e.g. "claude-haiku-4-5-20241022").
        """
        # Normalize None and empty string to the same "not configured" state.
        self.anthropic_api_key: str = anthropic_api_key or ""
        self.ollama_host: str = ollama_host.rstrip("/")
        self.ollama_model: str = ollama_model
        self.anthropic_model: str = anthropic_model

    def call(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 200,
        temperature: float = 0.3,
        cache_system_prompt: bool = False,
        json_output: bool = False,
    ) -> LLMResponse:
        """
        Send a prompt to the LLM with automatic Anthropic -> Ollama fallback.

        Args:
            prompt: The user prompt to send.
            system_prompt: Optional system message. Included when provided.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0–1.0).
            cache_system_prompt: If True and using Anthropic, apply prompt caching
                to the system message (cache_control={"type": "ephemeral"}).
            json_output: If True, appends a JSON-only instruction to the prompt and
                validates/parses the response as JSON. Raises LLMJSONParseError if
                the response cannot be parsed.

        Returns:
            LLMResponse with text, provider_used, token counts, etc.

        Raises:
            LLMJSONParseError: When json_output=True but response is not valid JSON.
            LLMUnavailableError: When all providers fail.
        """
        actual_prompt = prompt
        if json_output:
            actual_prompt = (
                prompt
                + "\n\nRespond with valid JSON only. No markdown fences, no prose."
            )

        # --- Tier 1: Anthropic ---
        if self.anthropic_api_key:
            try:
                response = self._call_anthropic(
                    actual_prompt, system_prompt, max_tokens, temperature, cache_system_prompt
                )
                if json_output:
                    response.text = self._parse_json_output(response.text)
                return response
            except LLMJSONParseError:
                raise  # JSON parse errors are not provider failures; don't fall back
            except Exception as exc:
                logger.warning(
                    "Anthropic call failed (%s: %s), falling back to Ollama",
                    type(exc).__name__, exc,
                )

        # --- Tier 2: Ollama ---
        try:
            response = self._call_ollama(actual_prompt, system_prompt, max_tokens, temperature)
            if json_output:
                response.text = self._parse_json_output(response.text)
            return response
        except LLMJSONParseError:
            raise
        except Exception as exc:
            logger.error("Ollama call also failed (%s: %s)", type(exc).__name__, exc)
            raise LLMUnavailableError(
                f"All LLM providers failed. Last error: {type(exc).__name__}: {exc}"
            ) from exc

    def check_ollama_connectivity(self) -> bool:
        """
        Ping Ollama at the configured host. Returns True if reachable, False otherwise.

        Used for startup health checks. Catches all exceptions and returns False
        so callers can log a warning and continue (Anthropic may still be available).

        Returns:
            True if Ollama responded with HTTP 200, False on any error.
        """
        url = f"{self.ollama_host}/api/tags"
        try:
            resp = requests.get(url, timeout=5)
            reachable = resp.status_code == 200
            if reachable:
                logger.info("Ollama health check passed at %s", self.ollama_host)
            else:
                logger.warning(
                    "Ollama health check returned %d at %s", resp.status_code, self.ollama_host
                )
            return reachable
        except Exception as exc:
            logger.warning(
                "Ollama health check failed (%s): %s", type(exc).__name__, exc
            )
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_anthropic(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        cache_system_prompt: bool,
    ) -> LLMResponse:
        """Send a request to the Anthropic API and return LLMResponse.

        Raises any Anthropic SDK or network exception so the caller can decide
        whether to fall back to Ollama.
        """
        kwargs: dict = {
            "model": self.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system_prompt:
            if cache_system_prompt:
                # Prompt caching: wrap system content with cache_control block.
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                kwargs["system"] = system_prompt

        logger.debug(
            "Anthropic request: model=%s max_tokens=%d cache=%s",
            self.anthropic_model, max_tokens, cache_system_prompt,
        )

        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        response = client.messages.create(**kwargs)

        raw_text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        tokens_in: int = response.usage.input_tokens
        tokens_out: int = response.usage.output_tokens
        cached: bool = getattr(response.usage, "cache_read_input_tokens", 0) > 0

        logger.debug(
            "Anthropic response: tokens_in=%d tokens_out=%d cached=%s",
            tokens_in, tokens_out, cached,
        )

        return LLMResponse(
            text=raw_text,
            provider_used="anthropic",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached=cached,
            model=self.anthropic_model,
        )

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """POST to Ollama /api/generate and return LLMResponse.

        LESSONS: stream must be False (not omitted) to get a single JSON response.
        """
        url = f"{self.ollama_host}/api/generate"
        body: dict = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            body["system"] = system_prompt

        logger.debug("Ollama request: model=%s url=%s", self.ollama_model, url)

        resp = requests.post(url, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        raw_text: str = data.get("response", "")
        logger.debug("Ollama response: %r", raw_text[:200])

        return LLMResponse(
            text=raw_text,
            provider_used="ollama",
            model=self.ollama_model,
        )

    def _parse_json_output(self, text: str) -> str:
        """Strip markdown code fences and validate that the text is valid JSON.

        Args:
            text: Raw LLM response text, possibly wrapped in ```json fences.

        Returns:
            The cleaned text (fence-stripped, whitespace-trimmed) if it is
            valid JSON.

        Raises:
            LLMJSONParseError: If the cleaned text cannot be parsed as JSON.
                The raw_text attribute of the exception contains the original text.
        """
        cleaned = _JSON_FENCE_RE.sub("", text).strip()
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError as exc:
            logger.error(
                "LLM response is not valid JSON: %s | raw: %r", exc, text[:500]
            )
            raise LLMJSONParseError(
                f"LLM response is not valid JSON: {exc}",
                raw_text=text,
            ) from exc
