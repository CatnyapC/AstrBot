# Provider Request Pipeline Diagnostics

AstrBot logs explicit provider-request handoff points for plugin-triggered LLM
requests. These logs are intended for debugging cases where a plugin yields a
`ProviderRequest`, but no `OnLLMRequestEvent` hook runs.

Current diagnostic points:

- `ProcessStage provider_request handoff`: `ProviderRequest` was yielded by a
  plugin handler and passed to the agent request stage.
- `AgentRequestSubStage enter`: the request reached the provider-request stage.
- `AgentRequestSubStage skip`: provider settings or session settings blocked
  the request before the agent runner.
- `InternalAgentSubStage waiting session lock`: request is about to wait on the
  per-session LLM lock.
- `InternalAgentSubStage acquired session lock`: request passed the session
  lock; the wait time is included.
- `InternalAgentSubStage calling OnLLMRequestEvent`: plugin hooks are about to
  receive the final `ProviderRequest`.
- `InternalAgentSubStage OnLLMRequestEvent returned`: hook dispatch completed,
  including whether a hook consumed the request.

Thread Router timeout dispatch sets `_router_timeout_dispatched`, so these
diagnostics are emitted at info level for that path without changing routing
behavior.
