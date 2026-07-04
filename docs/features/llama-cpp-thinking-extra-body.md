# llama.cpp Thinking Extra Body

OpenAI-compatible llama.cpp providers use chat-template kwargs to control template-time thinking.

AstrBot accepts this provider extra body on provider IDs or source IDs starting with `llama_cpp`:

```json
{
  "enable_thinking": false
}
```

Before the OpenAI SDK call, AstrBot maps it to:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

This is intentionally limited to `llama_cpp*` providers. Other OpenAI-compatible providers keep top-level `enable_thinking`, because services such as Qwen/DashScope may define that shape themselves.
