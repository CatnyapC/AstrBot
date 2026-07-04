# Features Docs

Use this folder for feature-level documentation.

## Available Docs

- `future-task-management.md`: future task / cron feature, execution model, API and WebUI behavior, and current limits.
- `gemma4-audio-fastapi-service.md`: local macOS FastAPI service for Gemma 4 E4B native audio analysis.
- `gpt-sovits-tts.md`: local GPT-SoVITS `api_v2.py` sidecar setup for AstrBot TTS.
- `llama-cpp-thinking-extra-body.md`: llama.cpp OpenAI-compatible providers map top-level `enable_thinking` into `chat_template_kwargs`.
- `media-component-url-fallback.md`: incoming media components whose `file` only carries a platform filename now fall back to `url` for local download.
- `provider-request-pipeline-diagnostics.md`: info-level checkpoints for plugin-yielded LLM `ProviderRequest` handoff and hook dispatch.
- `provider-runtime-chat-kwargs.md`: provider payload boundary for runner-only chat kwargs such as abort signals.
- `thread-archive-media-caption-providers.md`: thread archive caption provider selection for image, video, and record media.
- `webui-config-metadata-i18n.md`: why WebUI config metadata shows `[MISSING: features.config-metadata...]` and how to fix/rebuild served dashboard assets.
