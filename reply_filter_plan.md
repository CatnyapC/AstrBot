# Reply Filter Plugin Plan (Draft)

## Goal
Add a post-processing stage that runs **after the main LLM reply is generated** and **before sending**, to:
- Block unsafe or noisy outputs (e.g., stack traces, code dump, internal errors).
- Enforce language/style requirements by rewriting as needed.
- Preserve original reply when already compliant.

## Scope
- Initial target: text replies (plain text). Non-text (images/voice) can bypass.
- Default: all platforms supported by AstrBot, with per-platform opt-out.

## Architecture (Pipeline)
1. **Hook**: `@filter.on_decorating_result()` to intercept the final message chain before send.
2. **Rule Gate** (deterministic)
   - Regex/heuristic checks for code blocks, stack traces, exception strings.
   - If matched: return `BLOCK` or `REWRITE_REQUIRED`.
3. **LLM Post-Process** (conditional)
   - Trigger only when: rule gate flags OR language policy enabled.
   - Input: original reply + system constraints (language, tone, forbidden content).
   - Output contract: `{action: PASS|REWRITE|BLOCK, final_text?: "..."}`.
4. **Send**
   - PASS: send original.
   - REWRITE: send `final_text`.
   - BLOCK: send fallback message or suppress (configurable).

## Key Hook Decisions
- Use `@filter.on_decorating_result()` to mutate `event.get_result().chain` in-place.
- Only process `LLM_RESULT` to avoid intercepting tool/utility LLM calls.

## Config (Proposed)
- `enabled` (bool)
- `debug_mode` (bool)
- `provider_id` (string, optional override)
- `language_policy` (enum: `strict`, `soft`, `off`)
- `target_language` (string)
- `enable_llm_rewrite` (bool)
- `max_input_chars` / `max_output_chars` (int)
- `rule_gate_enable` (bool)
- `rule_gate_patterns` (list[str])
- `rule_gate_action` (enum: `block`, `rewrite`)
- `block_mode` (enum: `silent`, `fallback`)
- `block_fallback_text` (string)

## Prompts
- **Rewrite Prompt**: concise, deterministic instructions with explicit output JSON.
- **Language Constraint**: enforce target language and style (no code, no errors, no logs).

## Risks / Open Points
- Hook availability for post-processing across platforms.
- Avoid infinite loops if rewritten reply re-triggers post-processing.
- Ensure latency is acceptable; add short-circuit path.

## Implementation Steps
1. Identify correct hook point in AstrBot pipeline (LLM reply → send).
2. Implement rule gate and post-process LLM call.
3. Add configuration schema and defaults.
4. Add logging / debug mode for traceability.
5. Add tests for rule gate and prompt output parsing.
