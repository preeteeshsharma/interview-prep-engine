"""Tests for the LLM provider layer.

Coverage:
- LLMProvider Protocol: AnthropicProvider and GeminiProvider satisfy it structurally
- AnthropicProvider: complete(), complete_with_tools(), 429 retry, non-retryable raise
- GeminiProvider: complete(), complete_with_tools(), web_search → google_search mapping,
  message format conversion, safety-filter fallback text extraction
- llm_client facade: Gemini primary, Anthropic fallback on error, Anthropic-only when no Gemini
"""
from __future__ import annotations

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gemini_provider():
    """Create GeminiProvider bypassing __init__ so tests supply their own mock client."""
    from app.integrations.gemini_client import GeminiProvider
    provider = object.__new__(GeminiProvider)
    return provider


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

def test_anthropic_provider_satisfies_llm_protocol():
    from app.integrations.anthropic_client import AnthropicProvider
    assert inspect.iscoroutinefunction(AnthropicProvider.complete)
    assert inspect.iscoroutinefunction(AnthropicProvider.complete_with_tools)


def test_gemini_provider_satisfies_llm_protocol():
    from app.integrations.gemini_client import GeminiProvider
    assert inspect.iscoroutinefunction(GeminiProvider.complete)
    assert inspect.iscoroutinefunction(GeminiProvider.complete_with_tools)


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------

@pytest.fixture
def anthropic_provider():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="anthropic answer")]
    mock_api = AsyncMock(return_value=mock_response)

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = mock_api
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()

    # Swap the inner client reference so tests can reconfigure responses.
    provider._client = MagicMock()
    provider._client.messages.create = mock_api
    return provider, mock_api, mock_response


@pytest.mark.asyncio
async def test_anthropic_complete_returns_first_text_block():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="hello")]

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()
        result = await provider.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "hello"


@pytest.mark.asyncio
async def test_anthropic_complete_with_tools_joins_text_blocks():
    mock_response = MagicMock()
    b1 = MagicMock(text="part one")
    b2 = MagicMock(text="part two")
    b3 = MagicMock(spec=[])  # tool_use block — no text attr
    mock_response.content = [b1, b2, b3]

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()
        result = await provider.complete_with_tools(
            [{"role": "user", "content": "search"}],
            "sys",
            [{"type": "web_search_20250305", "name": "web_search"}],
        )

    assert result == "part one\n\npart two"


@pytest.mark.asyncio
async def test_anthropic_retries_on_429_with_rate_limit_wait(monkeypatch):
    import httpx
    from anthropic import APIStatusError

    mock_sleep = AsyncMock()
    monkeypatch.setattr("app.integrations.anthropic_client.asyncio.sleep", mock_sleep)

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rate_err = APIStatusError("rate limited", response=httpx.Response(429, request=req), body=None)
    good = MagicMock()
    good.content = [MagicMock(text="ok after retry")]

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=[rate_err, good])
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()
        result = await provider.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "ok after retry"
    # Must wait 65s (per-minute rate limit), not short exponential backoff.
    mock_sleep.assert_awaited_once_with(65)


@pytest.mark.asyncio
async def test_anthropic_raises_immediately_on_non_retryable_error():
    import httpx
    from anthropic import APIStatusError

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad_err = APIStatusError("bad request", response=httpx.Response(400, request=req), body=None)

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=bad_err)
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()

        with pytest.raises(APIStatusError):
            await provider.complete([{"role": "user", "content": "hi"}], "sys")

    # Only one attempt — no retries for 400.
    assert mock_client.messages.create.call_count == 1


# ---------------------------------------------------------------------------
# GeminiProvider — message format conversion (pure, no mocks needed)
# ---------------------------------------------------------------------------

def test_gemini_to_contents_converts_roles():
    from app.integrations.gemini_client import GeminiProvider
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "Question"},
    ]
    contents = GeminiProvider._to_contents(messages)
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"  # assistant → model
    assert contents[2]["role"] == "user"


def test_gemini_to_contents_handles_list_content():
    from app.integrations.gemini_client import GeminiProvider
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "hello"},
            {"type": "image", "source": "..."},  # non-text block — dropped
        ]},
    ]
    contents = GeminiProvider._to_contents(messages)
    assert len(contents[0]["parts"]) == 1
    assert contents[0]["parts"][0]["text"] == "hello"


def test_gemini_convert_tools_web_search_only():
    from google.genai import types
    from app.integrations.gemini_client import GeminiProvider

    result = GeminiProvider._convert_tools([{"type": "web_search_20250305", "name": "web_search"}])
    assert result is not None
    assert len(result) == 1
    assert isinstance(result[0], types.Tool)
    assert result[0].google_search is not None


def test_gemini_convert_tools_function_tool():
    from google.genai import types
    from app.integrations.gemini_client import GeminiProvider

    tools = [{
        "name": "get_weather",
        "description": "Get weather for a city",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["location"],
        },
    }]
    result = GeminiProvider._convert_tools(tools)
    assert result is not None
    assert len(result) == 1
    decl = result[0].function_declarations[0]
    assert decl.name == "get_weather"
    assert decl.description == "Get weather for a city"
    assert "location" in decl.parameters.properties
    assert decl.parameters.required == ["location"]


def test_gemini_convert_tools_mixed_web_search_and_function():
    from google.genai import types
    from app.integrations.gemini_client import GeminiProvider

    tools = [
        {"type": "web_search_20250305", "name": "web_search"},
        {
            "name": "save_note",
            "description": "Save a note",
            "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        },
    ]
    result = GeminiProvider._convert_tools(tools)
    assert result is not None
    # web search and function declarations are separate Tool objects
    tool_types = {("google_search" if t.google_search else "function") for t in result}
    assert "google_search" in tool_types
    assert "function" in tool_types


def test_gemini_convert_tools_empty_returns_none():
    from app.integrations.gemini_client import GeminiProvider
    assert GeminiProvider._convert_tools([]) is None


def test_gemini_schema_to_gemini_recursive():
    from google.genai import types
    from app.integrations.gemini_client import GeminiProvider

    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }
    result = GeminiProvider._schema_to_gemini(schema)
    assert result.type.name == "OBJECT"
    items_prop = result.properties["items"]
    assert items_prop.type.name == "ARRAY"
    assert items_prop.items.type.name == "STRING"


def test_gemini_has_web_search_detects_anthropic_tool():
    from app.integrations.gemini_client import GeminiProvider
    assert GeminiProvider._has_web_search([{"type": "web_search_20250305", "name": "web_search"}])
    assert not GeminiProvider._has_web_search([{"type": "custom_function", "name": "my_tool"}])
    assert not GeminiProvider._has_web_search([])


def test_gemini_extract_text_falls_back_on_safety_block():
    from app.integrations.gemini_client import GeminiProvider

    response = MagicMock()
    # Simulate safety filter: response.text raises ValueError
    type(response).text = property(lambda self: (_ for _ in ()).throw(ValueError("blocked")))
    part = MagicMock()
    part.text = "recovered text"
    response.candidates = [MagicMock(content=MagicMock(parts=[part]))]

    result = GeminiProvider._extract_text(response)
    assert result == "recovered text"


# ---------------------------------------------------------------------------
# GeminiProvider — async calls (mock client injected via object.__new__)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_complete_returns_text():
    from google.genai import types

    mock_response = MagicMock()
    mock_response.text = "gemini answer"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = _make_gemini_provider()
    provider._client = mock_client

    result = await provider.complete(
        [{"role": "user", "content": "hi"}],
        system="sys",
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
    )
    assert result == "gemini answer"
    # Confirm correct model mapping: Haiku → gemini-2.5-flash
    call_kwargs = mock_client.aio.models.generate_content.call_args
    assert call_kwargs.kwargs["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_gemini_complete_maps_sonnet_to_25_pro():
    mock_response = MagicMock(text="ok")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = _make_gemini_provider()
    provider._client = mock_client

    await provider.complete([{"role": "user", "content": "hi"}], "sys", model="claude-sonnet-4-6")
    call_kwargs = mock_client.aio.models.generate_content.call_args
    assert call_kwargs.kwargs["model"] == "gemini-2.5-pro"


@pytest.mark.asyncio
async def test_gemini_complete_with_tools_adds_google_search_for_web_search():
    from google.genai import types

    mock_response = MagicMock(text="search result")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = _make_gemini_provider()
    provider._client = mock_client

    await provider.complete_with_tools(
        [{"role": "user", "content": "research"}],
        system="sys",
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    call_kwargs = mock_client.aio.models.generate_content.call_args
    config: types.GenerateContentConfig = call_kwargs.kwargs["config"]
    assert config.tools is not None
    assert len(config.tools) == 1
    assert isinstance(config.tools[0], types.Tool)
    assert config.tools[0].google_search is not None


@pytest.mark.asyncio
async def test_gemini_complete_with_tools_converts_function_tool():
    from google.genai import types

    mock_response = MagicMock(text="ok")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = _make_gemini_provider()
    provider._client = mock_client

    await provider.complete_with_tools(
        [{"role": "user", "content": "hi"}],
        system="sys",
        tools=[{"name": "my_custom_tool", "description": "does something",
                "input_schema": {"type": "object", "properties": {}}}],
    )

    call_kwargs = mock_client.aio.models.generate_content.call_args
    config: types.GenerateContentConfig = call_kwargs.kwargs["config"]
    # Custom function tool must be converted to a FunctionDeclaration, not dropped.
    assert config.tools is not None
    assert config.tools[0].function_declarations[0].name == "my_custom_tool"


@pytest.mark.asyncio
async def test_gemini_retries_on_server_error(monkeypatch):
    from google.genai.errors import ServerError

    mock_sleep = AsyncMock()
    monkeypatch.setattr("app.integrations.gemini_client.asyncio.sleep", mock_sleep)

    mock_response = MagicMock(text="ok after retry")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[ServerError("internal error", {"error": {"message": "server error"}}), mock_response]
    )

    provider = _make_gemini_provider()
    provider._client = mock_client

    result = await provider.complete([{"role": "user", "content": "hi"}], "sys")
    assert result == "ok after retry"
    mock_sleep.assert_awaited_once()


def test_gemini_uses_vertex_ai_when_project_set(monkeypatch):
    """When GOOGLE_CLOUD_PROJECT is set, genai.Client is called with vertexai=True."""
    import json
    sa_json = json.dumps({"type": "service_account", "project_id": "test-project"})
    mock_settings = MagicMock(
        google_cloud_project="test-project",
        google_cloud_location="us-central1",
        vertex_service_account_json=sa_json,
        gemini_api_key="",
    )
    monkeypatch.setattr("app.integrations.gemini_client.settings", mock_settings)

    mock_client_instance = MagicMock()
    mock_creds = MagicMock()

    with patch("google.genai.Client", return_value=mock_client_instance) as mock_genai_client, \
         patch("google.oauth2.service_account.Credentials.from_service_account_info", return_value=mock_creds):
        from app.integrations.gemini_client import GeminiProvider
        provider = GeminiProvider()

    assert provider._client is mock_client_instance
    call_kwargs = mock_genai_client.call_args.kwargs
    assert call_kwargs.get("vertexai") is True
    assert call_kwargs.get("project") == "test-project"
    assert call_kwargs.get("location") == "us-central1"
    assert call_kwargs.get("credentials") is mock_creds


@pytest.mark.asyncio
async def test_gemini_raises_on_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.gemini_client.settings",
        MagicMock(gemini_api_key="", google_cloud_project="", google_cloud_location="us-central1", vertex_service_account_json=""),
    )
    from app.integrations.gemini_client import GeminiProvider

    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT|GEMINI_API_KEY"):
        GeminiProvider()


def test_gemini_model_mapping_defaults_to_25_pro():
    from app.integrations.gemini_client import GeminiProvider
    provider = _make_gemini_provider()
    assert provider._model("claude-haiku-4-5-20251001") == "gemini-2.5-flash"
    assert provider._model("claude-sonnet-4-6") == "gemini-2.5-pro"
    assert provider._model("claude-opus-4-7") == "gemini-2.5-pro"
    assert provider._model("some-unknown-model") == "gemini-2.5-pro"  # default


@pytest.mark.asyncio
async def test_gemini_retries_on_rate_limit_client_error(monkeypatch):
    from google.genai.errors import ClientError

    mock_sleep = AsyncMock()
    monkeypatch.setattr("app.integrations.gemini_client.asyncio.sleep", mock_sleep)

    rate_err = ClientError("429 quota exceeded", {"error": {"code": 429, "message": "quota"}})
    mock_response = MagicMock(text="ok after rate limit wait")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[rate_err, mock_response])

    provider = _make_gemini_provider()
    provider._client = mock_client

    result = await provider.complete([{"role": "user", "content": "hi"}], "sys")
    assert result == "ok after rate limit wait"
    mock_sleep.assert_awaited_once_with(65)  # _RATE_LIMIT_WAIT, not exponential


@pytest.mark.asyncio
async def test_anthropic_complete_with_tools_retries_on_429(monkeypatch):
    import httpx
    from anthropic import APIStatusError

    mock_sleep = AsyncMock()
    monkeypatch.setattr("app.integrations.anthropic_client.asyncio.sleep", mock_sleep)

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rate_err = APIStatusError("rate limited", response=httpx.Response(429, request=req), body=None)
    good = MagicMock()
    good.content = [MagicMock(text="tools result")]

    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=[rate_err, good])
        from app.integrations.anthropic_client import AnthropicProvider
        provider = AnthropicProvider()
        result = await provider.complete_with_tools(
            [{"role": "user", "content": "search"}],
            "sys",
            [{"type": "web_search_20250305", "name": "web_search"}],
        )

    assert result == "tools result"
    mock_sleep.assert_awaited_once_with(65)


# ---------------------------------------------------------------------------
# llm_client facade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_facade_uses_gemini_as_primary(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(return_value="gemini response")
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic response")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "gemini response"
    mock_gemini.complete.assert_awaited_once()
    mock_anthropic.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_facade_falls_back_to_anthropic_when_gemini_fails(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(side_effect=RuntimeError("gemini down"))
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic fallback")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "anthropic fallback"
    mock_anthropic.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_facade_uses_only_anthropic_when_gemini_not_configured(monkeypatch):
    import app.integrations.llm_client as facade

    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic only")

    monkeypatch.setattr(facade, "_gemini", None)  # no Gemini key configured
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="anthropic")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "anthropic only"
    mock_anthropic.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_facade_complete_with_tools_falls_back_on_gemini_error(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete_with_tools = AsyncMock(side_effect=RuntimeError("quota"))
    mock_anthropic = MagicMock()
    mock_anthropic.complete_with_tools = AsyncMock(return_value="anthropic tools result")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete_with_tools(
            [{"role": "user", "content": "research"}],
            "sys",
            [{"type": "web_search_20250305", "name": "web_search"}],
        )

    assert result == "anthropic tools result"
    mock_anthropic.complete_with_tools.assert_awaited_once()
