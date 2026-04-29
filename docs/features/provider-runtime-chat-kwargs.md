# Provider Runtime Chat Kwargs

Agent runners may pass runtime-only controls to providers through `text_chat(...)`, such as `abort_signal` for stopping in-flight tool loops.

OpenAI-compatible providers must not forward those controls into API request payloads. Only API-supported chat fields should reach `chat.completions.create(...)`; runtime controls stay inside AstrBot.
