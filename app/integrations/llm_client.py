"""Unified LLM facade with two tiers:

  complete() / complete_with_tools()
      Claude primary → Gemini fallback.
      Use for reasoning, research, interview, coaching — quality matters.

  complete_fast() / complete_fast_with_tools()
      Gemini Flash primary → Claude Haiku fallback.
      Use for classification, parsing, scoring — speed and cost matter.
"""
from __future__ import annotations

from app.config import settings
from app.integrations.anthropic_client import AnthropicProvider, ResponseTruncatedError
from app.integrations.llm_interface import LLMProvider
from app.lib.app_config import get as get_config
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
    "claude-sonnet-4-6": 6000,
    "claude-opus-4-7": 6000,
}

_anthropic: LLMProvider = AnthropicProvider()

# Gemini is primary when Vertex AI (GOOGLE_CLOUD_PROJECT) or direct API key is configured.
_gemini: LLMProvider | None = None
if settings.google_cloud_project or settings.gemini_api_key:
    from app.integrations.gemini_client import GeminiProvider
    _gemini = GeminiProvider()


async def _primary() -> LLMProvider:
    provider = await get_config("llm.primary_provider")
    return _gemini if (provider == "gemini" and _gemini is not None) else _anthropic


async def _fast() -> LLMProvider:
    provider = await get_config("llm.fast_provider")
    return _gemini if (provider == "gemini" and _gemini is not None) else _anthropic


def _fallback(primary: LLMProvider) -> LLMProvider | None:
    return _gemini if primary is _anthropic else _anthropic


async def complete(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS.get(model, 1024)
    primary = await _primary()
    try:
        result = await primary.complete(messages, system, model, tokens)
        logger.debug("llm.provider", provider=type(primary).__name__, model=model)
        return result
    except Exception as exc:
        fallback = _fallback(primary)
        if fallback is None:
            raise
        logger.warning("llm.primary_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
    try:
        return await fallback.complete(messages, system, model, tokens)
    except Exception as exc:
        logger.error("llm.fallback_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
        raise


async def complete_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS_TOOLS.get(model, 4096)
    primary = await _primary()
    try:
        result = await primary.complete_with_tools(messages, system, tools, model, tokens)
        logger.debug("llm.provider", provider=type(primary).__name__, model=model)
        return result
    except ResponseTruncatedError as exc:
        fallback = _fallback(primary)
        if fallback is None:
            raise
        logger.warning("llm.truncated_falling_back", error=str(exc), fallback=type(fallback).__name__)
    except Exception as exc:
        fallback = _fallback(primary)
        if fallback is None:
            raise
        logger.warning("llm.primary_tools_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
    try:
        return await fallback.complete_with_tools(messages, system, tools, model, tokens)
    except Exception as exc:
        logger.error("llm.fallback_tools_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Fast tier — reads llm.fast_provider from config (default: gemini)
# ---------------------------------------------------------------------------

_FAST_MODEL = "claude-haiku-4-5-20251001"


async def complete_fast(
    messages: list[dict],
    system: str,
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS.get(_FAST_MODEL, 512)
    fast = await _fast()
    try:
        result = await fast.complete(messages, system, _FAST_MODEL, tokens)
        logger.debug("llm.provider", provider=type(fast).__name__ + "-fast", model=_FAST_MODEL)
        return result
    except Exception as exc:
        fallback = _fallback(fast)
        if fallback is None:
            raise
        logger.warning("llm.fast_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
    try:
        return await fallback.complete(messages, system, _FAST_MODEL, tokens)
    except Exception as exc:
        logger.error("llm.fast_fallback_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
        raise


async def complete_fast_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS_TOOLS.get(_FAST_MODEL, 1024)
    fast = await _fast()
    try:
        result = await fast.complete_with_tools(messages, system, tools, _FAST_MODEL, tokens)
        logger.debug("llm.provider", provider=type(fast).__name__ + "-fast", model=_FAST_MODEL)
        return result
    except Exception as exc:
        fallback = _fallback(fast)
        if fallback is None:
            raise
        logger.warning("llm.fast_tools_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
    try:
        return await fallback.complete_with_tools(messages, system, tools, _FAST_MODEL, tokens)
    except Exception as exc:
        logger.error("llm.fast_tools_fallback_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
        raise
