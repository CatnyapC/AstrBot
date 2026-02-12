# Lexicon/Style Skill Plan (Huomi)

## Goal
Create a lightweight “用语规范” skill that normalizes specific expressions (e.g., “的人” → “的兽/的狐”) without heavy post-processing, and can be adjusted without code changes.

## Scope
- Applies to Huomi’s replies (and optionally other personas if configured later).
- Focus on phrasing normalization and small stylistic rules only.
- No memory, no sentiment, no world-knowledge changes.

## Inputs
- Static rule table (configurable):
  - Exact replacements (string -> string)
  - Pattern-based replacements (regex -> template)
- Optional entity hints (e.g., target species) if available.

## Outputs
- A normalized reply with consistent vocabulary rules.

## Proposed Architecture
1. Rule Table
   - Define in config (JSON/YAML) with two lists:
     - `literal_rules`: list of {from, to}
     - `regex_rules`: list of {pattern, replace, flags}
2. Execution Hook
   - Use a light, deterministic pass before sending (or as a skill tool invoked by the system prompt).
3. Persona Scope
   - Default: only “狐米” (configurable list).
4. Fallback Behavior
   - If no species known, default to “兽”.

## Implementation Steps
1. Create a skill or lightweight plugin module for lexicon normalization.
2. Add config schema with rules + persona scope.
3. Integrate into output pipeline (before/after action-fix) with clear order.
4. Add logs in debug mode to show applied rules.
5. Test with 3–5 sample inputs.

## Open Questions
- Where to read target species from (impression card? explicit mentions?)
- Should this run before or after action-fix rewrite?

