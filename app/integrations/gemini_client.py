from __future__ import annotations

import asyncio

from google.genai import errors as genai_errors

from app.config import settings
from app.lib.logging import get_logger

logger = get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2
_RATE_LIMIT_WAIT = 65

_MODEL_MAP: dict[str, str] = {
    "claude-sonnet-4-6": "gemini-2.5-pro",
    "claude-opus-4-7": "gemini-2.5-pro",
    "claude-haiku-4-5-20251001": "gemini-2.0-flash",
}


class GeminiProvider:
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        from google import genai
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def _model(self, anthropic_model: str) -> str:
        return _MODEL_MAP.get(anthropic_model, "gemini-2.5-pro")

    @staticmethod
    def _to_contents(messages: list[dict]) -> list[dict]:
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            raw = msg["content"]
            if isinstance(raw, str):
                parts = [{"text": raw}]
            elif isinstance(raw, list):
                parts = [{"text": b["text"]} for b in raw if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
            else:
                parts = [{"text": str(raw)}]
            if parts:
                contents.append({"role": role, "parts": parts})
        return contents

    @staticmethod
    def _extract_text(response) -> str:
        try:
            return response.text
        except (ValueError, AttributeError):
            parts = []
            for candidate in getattr(response, "candidates", []):
                for part in getattr(candidate.content, "parts", []):
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
            return "\n\n".join(parts)

    @staticmethod
    def _has_web_search(tools: list[dict]) -> bool:
        return any(t.get("type") == "web_search_20250305" or t.get("name") == "web_search" for t in tools)

    async def complete(
        self,
        messages: list[dict],
        system: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 1024,
    ) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        contents = self._to_contents(messages)

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model(model),
                    contents=contents,
                    config=config,
                )
                return self._extract_text(response)
            except genai_errors.ServerError as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("gemini.retrying", attempt=attempt + 1, wait=wait, error=str(exc))
                    await asyncio.sleep(wait)
                    continue
                raise
            except genai_errors.ClientError as exc:
                if "429" in str(exc) or "quota" in str(exc).lower():
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning("gemini.rate_limit", attempt=attempt + 1, wait=_RATE_LIMIT_WAIT)
                        await asyncio.sleep(_RATE_LIMIT_WAIT)
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
        from google.genai import types

        gemini_tools = None
        if self._has_web_search(tools):
            # Anthropic web_search_20250305 → Gemini Google Search grounding.
            gemini_tools = [types.Tool(google_search=types.GoogleSearch())]

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=gemini_tools,
        )
        contents = self._to_contents(messages)

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model(model),
                    contents=contents,
                    config=config,
                )
                return self._extract_text(response)
            except genai_errors.ServerError as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("gemini.retrying", attempt=attempt + 1, wait=wait, error=str(exc))
                    await asyncio.sleep(wait)
                    continue
                raise
            except genai_errors.ClientError as exc:
                if "429" in str(exc) or "quota" in str(exc).lower():
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning("gemini.rate_limit", attempt=attempt + 1, wait=_RATE_LIMIT_WAIT)
                        await asyncio.sleep(_RATE_LIMIT_WAIT)
                        continue
                raise
