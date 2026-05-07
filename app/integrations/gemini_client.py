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

    @staticmethod
    def _schema_to_gemini(schema: dict):
        """Recursively convert an Anthropic JSON Schema dict to a Gemini types.Schema."""
        from google.genai import types

        _TYPE_MAP = {
            "string": "STRING", "number": "NUMBER", "integer": "INTEGER",
            "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT",
        }
        kwargs: dict = {
            "type": _TYPE_MAP.get((schema.get("type") or "string").lower(), "STRING"),
        }
        if "description" in schema:
            kwargs["description"] = schema["description"]
        if "properties" in schema:
            kwargs["properties"] = {
                k: GeminiProvider._schema_to_gemini(v)
                for k, v in schema["properties"].items()
            }
        if "required" in schema:
            kwargs["required"] = schema["required"]
        if "items" in schema:
            kwargs["items"] = GeminiProvider._schema_to_gemini(schema["items"])
        if "enum" in schema:
            kwargs["enum"] = schema["enum"]
        return types.Schema(**kwargs)

    @staticmethod
    def _convert_tools(tools: list[dict]):
        """Convert a list of Anthropic tool defs to Gemini Tool objects.

        web_search_20250305  → google_search grounding tool
        function tools       → FunctionDeclaration (one Tool per batch)
        """
        from google.genai import types

        gemini_tools = []
        function_decls = []

        for tool in tools:
            if tool.get("type") == "web_search_20250305" or tool.get("name") == "web_search":
                gemini_tools.append(types.Tool(google_search=types.GoogleSearch()))
            elif "name" in tool:
                schema = tool.get("input_schema", {"type": "object", "properties": {}})
                function_decls.append(
                    types.FunctionDeclaration(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        parameters=GeminiProvider._schema_to_gemini(schema),
                    )
                )

        if function_decls:
            gemini_tools.append(types.Tool(function_declarations=function_decls))

        return gemini_tools or None

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

        gemini_tools = self._convert_tools(tools)

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
