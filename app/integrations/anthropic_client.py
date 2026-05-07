import asyncio

from anthropic import AsyncAnthropic

from app.config import settings
from app.lib.logging import get_logger

logger = get_logger(__name__)

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2


async def complete(
    messages: list[dict],
    system: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> str:
    """Call Claude and return the text of the first content block.

    Retries up to 3 times on HTTP 529 (overloaded) with 2-second backoff.
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
        except Exception as exc:
            # anthropic SDK raises anthropic.APIStatusError for HTTP errors;
            # status_code 529 means the API is overloaded.
            status = getattr(exc, "status_code", None)
            if status == 529 and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    "anthropic.overloaded",
                    attempt=attempt + 1,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)
                continue
            raise
    # Unreachable — the loop always either returns or re-raises.
    raise RuntimeError("Exhausted retries without returning or raising")
