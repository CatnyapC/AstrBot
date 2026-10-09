# OpenRouter embedding routing

OpenAI-compatible embedding providers accept `custom_extra_body` in provider
configuration. Both `get_embedding` (including Dashboard availability tests) and
`get_embeddings` forward this dictionary through the SDK's `extra_body`. The
OpenAI Embedding template exposes the existing custom request-body editor.
Empty or non-dictionary values add no extra request parameters.

For `qwen_embedding`, the local routing configuration is:

```json
{
  "custom_extra_body": {
    "provider": {
      "order": ["nebius", "siliconflow/fp8", "deepinfra/us"],
      "only": ["nebius", "siliconflow/fp8", "deepinfra/us"],
      "allow_fallbacks": true
    }
  }
}
```

OpenRouter tries Nebius first, then SiliconFlow, then DeepInfra when an upstream
fails. `only` restricts fallback to these three endpoints. The model and dimensions
stay `qwen/qwen3-embedding-8b` and 4096; existing vector caches remain valid.
The active configuration lives in `data/cmd_config.json`, which contains secrets
and is not committed. Restart AstrBot after changing the adapter/configuration.

Two isolated same-host requests per endpoint on 2026-10-09 returned:

| Endpoint | Observed response time |
| --- | --- |
| Nebius | 1.09–1.24 seconds |
| SiliconFlow | 2.50–7.09 seconds |
| DeepInfra | One HTTP 429; successful request 11.17 seconds |

These small samples determine the initial preference order, not a latency SLA.
OpenRouter owns upstream failover; this adapter adds no separate retry loop.
An outer AIC Tag recall deadline of four seconds can still cancel a slow request
before provider fallback finishes. This routing change does not alter that budget.

See [OpenRouter embedding routing](https://openrouter.ai/docs/api_reference/embeddings)
and [provider ordering](https://openrouter.ai/docs/guides/routing/provider-selection).
