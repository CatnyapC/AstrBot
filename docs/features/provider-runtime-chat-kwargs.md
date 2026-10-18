# Provider Runtime Chat Kwargs

Agent runners may pass runtime-only controls to providers through `text_chat(...)`, such as `abort_signal` for stopping in-flight tool loops.

OpenAI-compatible providers must not forward those controls into API request payloads. Only API-supported chat fields should reach `chat.completions.create(...)`; runtime controls stay inside AstrBot.

For streaming and non-streaming calls, per-request extra-body fields override matching
`custom_extra_body` defaults. Nested values such as `reasoning` are replaced as
whole fields, not merged; unrelated provider routing/sampling defaults remain.
Provider-specific normalization still runs afterward. Request overrides never
modify the stored provider configuration or remove fields from the caller's
payload, so retries preserve their explicit overrides.
