import asyncio

from anthropic import APIConnectionError, APIStatusError, APITimeoutError, AsyncAnthropic

from app.config import settings
from app.lib.logging import get_logger

logger = get_logger(__name__)

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 2
_RETRYABLE_STATUSES = {429, 500, 502, 529}


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
                wait = _RETRY_BASE_SECONDS ** (attempt + 1)  # 2s, 4s
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
