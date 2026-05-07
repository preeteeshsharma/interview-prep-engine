from __future__ import annotations

import asyncio

from anthropic import APIConnectionError, APIStatusError, APITimeoutError, AsyncAnthropic

class ResponseTruncatedError(RuntimeError):
    """Raised when the model hits max_tokens — caller should fall back to another provider."""

from app.config import settings
from app.lib.logging import get_logger

logger = get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2
_RETRYABLE_STATUSES = {429, 500, 502, 529}
_RATE_LIMIT_WAIT = 65


class AnthropicProvider:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def complete(
        self,
        messages: list[dict],
        system: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 1024,
    ) -> str:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                if response.stop_reason == "max_tokens":
                    logger.warning("anthropic.truncated", model=model, max_tokens=max_tokens)
                return response.content[0].text
            except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
                status = getattr(exc, "status_code", None)
                retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or status in _RETRYABLE_STATUSES
                if retryable and attempt < _MAX_RETRIES - 1:
                    wait = _RATE_LIMIT_WAIT if status == 429 else _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("anthropic.retrying", attempt=attempt + 1, wait_seconds=wait, error=str(exc))
                    await asyncio.sleep(wait)
                    continue
                raise

    async def complete_with_tools(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
    ) -> str:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    system=system,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                )
                if response.stop_reason == "max_tokens":
                    logger.warning("anthropic.truncated", model=model, max_tokens=max_tokens)
                    raise ResponseTruncatedError(f"max_tokens={max_tokens} hit on {model}")
                texts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n\n".join(texts)
            except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
                status = getattr(exc, "status_code", None)
                retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or status in _RETRYABLE_STATUSES
                if retryable and attempt < _MAX_RETRIES - 1:
                    wait = _RATE_LIMIT_WAIT if status == 429 else _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("anthropic.retrying", attempt=attempt + 1, wait_seconds=wait, error=str(exc))
                    await asyncio.sleep(wait)
                    continue
                raise
