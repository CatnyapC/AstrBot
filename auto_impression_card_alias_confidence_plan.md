# Alias Confidence Plan (Trust + Decay)

## Current Alias Scope (Confirm)
- Alias mapping is scoped by `(group_id, speaker_id, alias, target_id)`.
- This means **each speaker maintains their own alias mapping to each target**.
- We will **keep this scoping unchanged**.

## Goal
Make `alias_map.confidence` reflect evidence quality using the same trust/decay logic used for traits/facts.

## Data Model
### Option A (Recommended): Reuse `impression_evidence`
- Store alias evidence as `item_type = "alias"`.
- `item_text` format: `"alias=<alias>"` (or `"alias:<alias>"`).
- Keep existing `(group_id, user_id)` = target_id.
- Add `speaker_id` for trust and `source_type/joke_likelihood` as in current evidence.

### Option B: New `alias_evidence` table
- If we want isolation, add a dedicated table mirroring evidence columns.

## LLM Outputs (Alias Analysis)
Extend alias analysis to output optional:
- `evidence_confidence`
- `joke_likelihood`
- `source_type` (self/other)

If unavailable, fall back to defaults.

## Confidence Formula
Reuse the same formula:
```
signal = evidence_confidence * (1 - joke) * source_weight * trust_weight * decay
alias_conf = 1 - Π(1 - signal_i)
```

- `trust_weight` uses speaker trust
- `decay` uses evidence half-life (same as traits/facts)

## Update Flow
1) Run alias analysis (LLM)
2) Insert alias evidence
3) Recompute `alias_map.confidence` from all alias evidence rows
4) Prune to top K per (speaker_id, target_id)

## Risks
- More writes per alias analysis
- Increased DB size (mitigated by evidence cap)

## TODO
- Decide evidence cap for alias (default = 3)
- Decide whether to use Option A (reuse impression_evidence) or Option B (alias_evidence)
