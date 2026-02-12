# Auto Impression Card: Summary + Plan (Draft)

## Goal
Add extra context to LLM responses using group member “portrait/Impression” data.

## Decisions So Far
- Use a plugin to inject extra context at LLM request time.
- Hook: `@filter.on_llm_request()` to modify `ProviderRequest` before LLM call.
- Plugin base: `astrbot_plugin_auto_impression_card` (template from `Soulter/helloworld`).

## Existing Pipeline Context (AstrBot)
- LLM request is built in `build_main_agent(...)` and then hooks are called.
- The LLM hook runs before actual provider call:
  - `InternalAgentSubStage.process(...)` calls `call_event_hook(EventType.OnLLMRequestEvent, req)`
- This makes `@filter.on_llm_request()` the correct injection point.

## Plugin Injection Strategy
- Add a handler with `@filter.on_llm_request()`.
- Inject “portrait” context via either:
  - `request.system_prompt += "..."` (stronger constraint)
  - `request.contexts.append({"role": "system", "content": "..."})` (structured)

## Portrait Source (Current Candidate)
Plugin cloned: `astrbot_plugin_portrayal`
- It generates portrait text on demand via:
  - message history scan (`MessageManager.get_user_texts`)
  - LLM analysis (`LLMService.generate_portrait`)
- It is currently **AIOCQHTTP-only** (uses `AiocqhttpMessageEvent`).
- There is **no public API**; portrait is generated via command handler.

## Implications
- If we reuse `astrbot_plugin_portrayal` code directly, the integration will be limited to AIOCQHTTP.
- For cross-platform, we likely need a new portrait provider or abstraction.

## Proposed Next Steps (Backwards from Goal)
1. Decide the portrait data source strategy:
   - A: Reuse `astrbot_plugin_portrayal` internals (AIOCQHTTP only)
   - B: Build portrait extraction in our plugin (more work, cross-platform)
   - C: Modify `astrbot_plugin_portrayal` to expose an API/adapter
2. Implement `@filter.on_llm_request()` in `astrbot_plugin_auto_impression_card`:
   - Placeholder injection first
   - Later replace with real portrait retrieval
3. Decide injection format and scope:
   - `system_prompt` vs `contexts`
   - group scope: `group_id` vs `unified_msg_origin`

## Files Touched
- `/Users/lincoln/Git/AstrBot/data/plugins/astrbot_plugin_auto_impression_card/metadata.yaml`
- `/Users/lincoln/Git/AstrBot/data/plugins/astrbot_plugin_auto_impression_card/main.py`

