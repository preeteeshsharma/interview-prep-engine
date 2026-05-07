"""Unified LLM facade with two tiers:

  complete() / complete_with_tools()
      Claude primary → Gemini fallback.
      Use for reasoning, research, interview, coaching — quality matters.

  complete_fast() / complete_fast_with_tools()
      Gemini Flash primary → Claude Haiku fallback.
      Use for classification, parsing, scoring — speed and cost matter.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

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


async def _with_fallback(
    primary: LLMProvider,
    call: Callable[[LLMProvider], Awaitable[str]],
    log_prefix: str,
    truncation_fallback: bool = False,
) -> str:
    """Run call(primary); on failure log and retry with fallback provider."""
    try:
        result = await call(primary)
        logger.debug("llm.provider", provider=type(primary).__name__)
        return result
    except ResponseTruncatedError as exc:
        if not truncation_fallback:
            raise
        fallback = _fallback(primary)
        if fallback is None:
            raise
        logger.warning("llm.truncated_falling_back", error=str(exc), fallback=type(fallback).__name__)
    except Exception as exc:
        fallback = _fallback(primary)
        if fallback is None:
            raise
        logger.warning(f"{log_prefix}_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)

    try:
        return await call(fallback)
    except Exception as exc:
        logger.error(f"{log_prefix}_fallback_failed", error=str(exc), fallback=type(fallback).__name__, exc_info=True)
        raise


async def complete(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS.get(model, 1024)
    primary = await _primary()
    return await _with_fallback(
        primary,
        lambda p: p.complete(messages, system, model, tokens),
        "llm.primary",
    )


async def complete_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS_TOOLS.get(model, 4096)
    primary = await _primary()
    return await _with_fallback(
        primary,
        lambda p: p.complete_with_tools(messages, system, tools, model, tokens),
        "llm.primary_tools",
        truncation_fallback=True,
    )


# ---------------------------------------------------------------------------
# Fast tier
# ---------------------------------------------------------------------------

_FAST_MODEL = "claude-haiku-4-5-20251001"


async def complete_fast(
    messages: list[dict],
    system: str,
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS.get(_FAST_MODEL, 512)
    fast = await _fast()
    return await _with_fallback(
        fast,
        lambda p: p.complete(messages, system, _FAST_MODEL, tokens),
        "llm.fast",
    )


async def complete_fast_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    max_tokens: int | None = None,
) -> str:
    tokens = max_tokens or _MAX_TOKENS_TOOLS.get(_FAST_MODEL, 1024)
    fast = await _fast()
    return await _with_fallback(
        fast,
        lambda p: p.complete_with_tools(messages, system, tools, _FAST_MODEL, tokens),
        "llm.fast_tools",
    )
