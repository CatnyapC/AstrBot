import json

import httpx
import pytest

from astrbot.core.provider.sources.openai_embedding_source import (
    OpenAIEmbeddingProvider,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize(
    "extra_body",
    [
        {
            "provider": {
                "order": ["nebius", "siliconflow/fp8", "deepinfra/us"],
                "only": ["nebius", "siliconflow/fp8", "deepinfra/us"],
                "allow_fallbacks": True,
            }
        },
        {},
        None,
        "invalid",
    ],
)
async def test_embedding_requests_forward_custom_extra_body(batch, extra_body):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "embedding-test",
                "data": [{"object": "embedding", "index": 0, "embedding": [1, 0]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    provider = OpenAIEmbeddingProvider(
        {
            "id": "embedding-test",
            "embedding_api_key": "test-key",
            "embedding_api_base": "https://embedding.test/v1",
            "embedding_model": "embedding-test",
            "embedding_dimensions": 2,
            "custom_extra_body": extra_body,
        },
        {},
    )
    await provider.client.close()
    provider.client = provider.client.with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )
    try:
        result = (
            await provider.get_embeddings(["astrbot"])
            if batch
            else await provider.get_embedding("astrbot")
        )
    finally:
        await provider.terminate()

    assert result == ([[1, 0]] if batch else [1, 0])
    payload = requests[0]
    assert payload["dimensions"] == 2
    assert payload["input"] == (["astrbot"] if batch else "astrbot")
    if isinstance(extra_body, dict) and extra_body:
        assert payload["provider"] == extra_body["provider"]
    else:
        assert "provider" not in payload
