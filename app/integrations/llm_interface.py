from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict],
        system: str,
        model: str,
        max_tokens: int,
    ) -> str: ...

    async def complete_with_tools(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> str: ...
