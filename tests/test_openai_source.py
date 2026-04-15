import asyncio
from types import SimpleNamespace

import pytest

from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.sources.openai_source import (
    EmptyOrMalformedCompletionError,
    ProviderOpenAIOfficial,
)


def test_openai_parse_completion_rejects_missing_choices():
    provider = object.__new__(ProviderOpenAIOfficial)
    provider.reasoning_key = "reasoning_content"

    with pytest.raises(EmptyOrMalformedCompletionError):
        asyncio.run(provider._parse_openai_completion(SimpleNamespace(id="resp-1", choices=None), None))


@pytest.mark.asyncio
async def test_openai_text_chat_retries_malformed_completion_once(monkeypatch):
    provider = object.__new__(ProviderOpenAIOfficial)
    provider.api_keys = ["k1"]
    provider.client = SimpleNamespace(api_key=None)
    provider.provider_config = {}

    async def _fake_prepare_chat_payload(*args, **kwargs):
        return {"messages": [], "model": "deepseek-chat"}, []

    calls = {"count": 0}

    async def _fake_query(payloads, tools):
        del payloads, tools
        calls["count"] += 1
        if calls["count"] == 1:
            raise EmptyOrMalformedCompletionError("missing completion.choices")
        return LLMResponse("assistant", completion_text="ok")

    async def _fake_sleep(_seconds):
        return None

    provider._prepare_chat_payload = _fake_prepare_chat_payload
    provider._query = _fake_query
    monkeypatch.setattr("astrbot.core.provider.sources.openai_source.asyncio.sleep", _fake_sleep)

    resp = await provider.text_chat(prompt="hello")

    assert resp.completion_text == "ok"
    assert calls["count"] == 2
