import asyncio

from anthropic import APIConnectionError, APIStatusError, APITimeoutError, AsyncAnthropic

from app.config import settings
from app.lib.logging import get_logger

logger = get_logger(__name__)

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2
_RETRYABLE_STATUSES = {429, 500, 502, 529}
# 429 is a per-minute rate limit — short backoff is useless; wait at least 60s.
_RATE_LIMIT_WAIT = 65


async def complete_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
) -> str:
    """Call Claude with tools (e.g. web_search) and return all text content joined."""
    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.messages.create(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
            # Collect all text blocks — web_search responses interleave tool_use + text
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


async def complete(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> str:
    """Call Claude and return the text of the first content block.

    Retries up to 3 times on transient errors (429/500/502/529, connection
    errors, timeouts) with exponential backoff (2s, 4s).
    """
    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.messages.create(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
            )
            return response.content[0].text
        except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
            status = getattr(exc, "status_code", None)
            retryable = isinstance(exc, (APIConnectionError, APITimeoutError)) or status in _RETRYABLE_STATUSES
            if retryable and attempt < _MAX_RETRIES - 1:
                wait = _RATE_LIMIT_WAIT if status == 429 else _RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "anthropic.retrying",
                    attempt=attempt + 1,
                    status=status,
                    wait_seconds=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)
                continue
            raise
