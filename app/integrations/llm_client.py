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
    max_tokens: int = 1024,
) -> str:
    if _gemini is not None:
        try:
            result = await _gemini.complete(messages, system, model, max_tokens)
            logger.debug("llm.provider", provider="gemini", model=model)
            return result
        except Exception as exc:
            logger.warning("llm.gemini_failed", error=str(exc), fallback="anthropic")
    return await _anthropic.complete(messages, system, model, max_tokens)


async def complete_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
) -> str:
    if _gemini is not None:
        try:
            result = await _gemini.complete_with_tools(messages, system, tools, model, max_tokens)
            logger.debug("llm.provider", provider="gemini", model=model)
            return result
        except Exception as exc:
            logger.warning("llm.gemini_tools_failed", error=str(exc), fallback="anthropic")
    return await _anthropic.complete_with_tools(messages, system, tools, model, max_tokens)
