# Trust Maintenance Plan (Pair Trust)

## Goal
Maintain a dynamic trust score for each pair (speaker -> target) to weight evidence when updating impressions.

## Scope
- Pair trust is used when a user A makes statements about user B.
- Falls back to global trust if pair trust is unavailable.

## Data Model
### Table: `user_trust`
- `group_id`
- `speaker_id`
- `target_id` (nullable for global trust)
- `trust` (0.0-1.0)
- `updated_at`

### Defaults
- Base trust: **0.7**
- If `pair trust` missing, derive from global trust:
  - `trust(A,B) = trust(A) * 0.9` (initial heuristic)

## Initialization (Simple & Practical)
- Admin/owner: 0.8
- Regular member: 0.7
- New/unknown: 0.6

## Update Timing
- Update trust **during impression update** (same run as Phase2/Phase3).

## Evidence-Driven Adjustments
Use evidence metadata from Phase1/Phase2:
- `evidence_confidence`
- `joke_likelihood`
- `source_type`
- `consistency` (consistent/neutral/conflicting)

### Reward/Penalty Rules (Simple Version)
- If evidence is **consistent** with current profile: +Δ
- If evidence is **conflicting**: -Δ
- If `joke_likelihood` is high: reduce Δ (or apply negative)
- If multiple independent speakers corroborate: additional +Δ

## Time Decay
Apply half-life decay to trust score on read or update:
```
trust = base + (trust - base) * exp(-Δt / half_life)
```
- base = 0.7
- half_life = 30 days

## Pair Trust Feasibility & Risks
- **Pros**: captures interpersonal reliability; avoids global bias.
- **Cons**: higher storage & update complexity; cold-start pairs are noisy.
- **Mitigation**: fallback to global trust; cap step size per update; decay to base.

## TODO
- Add admin commands to view/adjust trust.
- Decide whether to store separate global trust rows or compute from aggregates.
