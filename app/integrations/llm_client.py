"""Unified LLM facade: Gemini (primary) → Anthropic (fallback).

Both providers implement LLMProvider. All callers import complete() and
complete_with_tools() from here — provider selection is invisible to them.
"""
from __future__ import annotations

from app.config import settings
from app.integrations.anthropic_client import AnthropicProvider
from app.integrations.llm_interface import LLMProvider
from app.lib.logging import get_logger

logger = get_logger(__name__)

# Per-model token budgets — Gemini and Claude tokenize differently so a single
# global default causes truncation on one or wasteful limits on the other.
_MAX_TOKENS: dict[str, int] = {
    "claude-haiku-4-5-20251001": 512,
    "claude-sonnet-4-6": 1024,
    "claude-opus-4-7": 2048,
}
_MAX_TOKENS_TOOLS: dict[str, int] = {
    "claude-haiku-4-5-20251001": 1024,
    "claude-sonnet-4-6": 4096,
    "claude-opus-4-7": 4096,
}

_anthropic: LLMProvider = AnthropicProvider()

# Gemini is primary when Vertex AI (GOOGLE_CLOUD_PROJECT) or direct API key is configured.
_gemini: LLMProvider | None = None
if settings.google_cloud_project or settings.gemini_api_key:
    from app.integrations.gemini_client import GeminiProvider
    _gemini = GeminiProvider()


async def complete(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS.get(model, 1024)
    if _gemini is not None:
        try:
            result = await _gemini.complete(messages, system, model, tokens)
            logger.debug("llm.provider", provider="gemini", model=model)
            return result
        except Exception as exc:
            logger.warning("llm.gemini_failed", error=str(exc), fallback="anthropic")
    return await _anthropic.complete(messages, system, model, tokens)


async def complete_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS_TOOLS.get(model, 4096)
    if _gemini is not None:
        try:
            result = await _gemini.complete_with_tools(messages, system, tools, model, tokens)
            logger.debug("llm.provider", provider="gemini", model=model)
            return result
        except Exception as exc:
            logger.warning("llm.gemini_tools_failed", error=str(exc), fallback="anthropic")
    return await _anthropic.complete_with_tools(messages, system, tools, model, tokens)
