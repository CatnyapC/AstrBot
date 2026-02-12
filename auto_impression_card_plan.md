# Auto Impression Card: Backward Plan (Draft)

## Target Outcome
- Maintain a local impression profile for each group member.
- Profiles update as new messages arrive.
- The bot can inject a member’s profile into LLM context during interactions.
- The bot can answer queries about a specific member’s impression from the stored profile.

## Scope
- Platform: **QQ only** (AIOCQHTTP).

## Recommended Architecture
**One plugin with three pipelines: Collect → Update → Retrieve**

### 1) Collect
- Listen to group messages.
- Store message snippets keyed by `(group_id, user_id)`.
- Keep minimal data (text + timestamp + group_id).

### 2) Update
- Trigger update when threshold/time window is reached.
- Use LLM to merge new messages into an existing profile.
- Persist profile locally.

### 3) Retrieve
- On LLM request, inject the current speaker’s profile into context.
- Provide a command to query another member’s profile (e.g., `印象 @某人`).

## Use Existing AstrBot Features
- **Hook**: `@filter.on_llm_request()` for context injection.
- **Events**: group message event for collection.
- **Skills**: optional for retrieval tools.
- **SubAgent**: optional for portrait update.
- **Knowledge Base**: optional supplementary retrieval, not primary.
- **MCP**: optional if externalizing profile storage later.

## Storage Decision
- Prefer **plugin-local SQLite** (independent DB) over extending AstrBot’s main DB.
- Rationale: lower risk, no core migration, plugin can be upgraded/removed safely.
- Location: plugin data directory, e.g. `plugin_data/astrbot_plugin_auto_impression_card/impressions.db`.

## Storage (Schema Concept)
Suggested schema per `(group_id, user_id)`:

```
{
  "group_id": "...",
  "user_id": "...",
  "nickname": "...",
  "last_seen": "...",
  "summary": "...",
  "traits": ["..."],
  "facts": ["..."],
  "examples": ["..."],
  "updated_at": "...",
  "version": 1
}
```

## Implementation Steps (Minimal Viable)
1. Storage layer (plugin-local SQLite) with `get_profile()` / `save_profile()`.
2. Message collection listener (group-only) with buffering.
3. Incremental update prompt (old profile + new messages → new profile).
4. LLM context injection via `@filter.on_llm_request()`.
5. Query command for profile retrieval.

## Risks / Open Points
- Rate limiting: avoid frequent LLM updates on active groups.
- Data privacy: define retention window and opt-out.
- Platform coverage: start with group-only, extend later.

## Added Constraints
- **Update trigger (dual threshold):** update when `new_message_count >= N` OR `time_since_last_update >= T`.
- **Injection strength/length limit:** inject only a bounded subset (e.g., summary + top traits) to avoid context bloat.
- **Alias -> user_id mapping:** resolve multiple nicknames/aliases across a group to the same `user_id`.

## Config (via `_conf_schema.json`)
- `enabled` (bool)
- `group_whitelist` (list[string])
- `update_msg_threshold` (int) default **50**
- `update_time_threshold_sec` (int) default **7200**
- `inject_max_chars` (int)
- `inject_max_traits` (int)
- `inject_max_facts` (int)
- `ignore_short_text_len` (int)
- `ignore_regex` (string)

## Alias Resolution Strategy (Ambiguity-safe)
**Problem:** different users may use the same alias for different targets. Avoid global alias mapping.

### Recommended Mapping (Scoped by speaker)
- Store aliases as `(group_id, speaker_id, alias) -> target_id`.
- This avoids collisions like two speakers both using “狐狸” for different people.

### Suggested Table (SQLite)
```
alias_map(
  group_id TEXT,
  speaker_id TEXT,
  alias TEXT,
  target_id TEXT,
  confidence REAL,
  updated_at INTEGER,
  PRIMARY KEY (group_id, speaker_id, alias, target_id)
)
```

### Resolution Flow
1. If message contains **@mention** or **reply**, use that user_id directly.
2. If explicit ID provided, use it.
3. Else, use `(group_id, speaker_id, alias)` to find candidates.
   - One match → use it.
   - Multiple matches → ask user to clarify.

### Auto-learning Alias (High-precision only)
- Only write alias when alignment is explicit:
  - alias + @mention in the same message
  - alias + reply target in the same message
- Avoid guessing from plain text.

---

# Two-Phase Impression Update Plan (2026-02-11)

## Goals
- Keep traits/facts compact while preserving evidence for “why” queries.
- Avoid passing full examples into the LLM prompt.
- Ensure evidence remains linked to traits/facts even if wording changes.
- Run updates per group (no cross-group context mixing).

## Overview
We will introduce a dedicated evidence table (`impression_evidence`) and switch to a four-step update pipeline. Semantic attribution (mapping messages to target users) must run before the extraction/merge steps.

## Phase 0: Semantic Attribution (Prerequisite)
- Input: pending messages (raw text with speaker IDs).
- Output: `message_id -> target_user_ids`.
- Purpose: ensure messages are attributed to the correct users before any trait/fact extraction.

## Phase 1: Candidate Extraction (No Existing Profile)
- Input: attributed pending messages for each target user.
- LLM output: candidate traits/facts, each with evidence message IDs.
- No existing profile is provided in this phase.

Example output:
```
{
  "users": {
    "user_id": {
      "traits": [{"text": "爱吃鱼", "evidence_ids": [123, 125]}],
      "facts": [{"text": "自称龙族", "evidence_ids": [124]}]
    }
  }
}
```

## Phase 2: Merge/Replace (With Existing Profile)
- Input:
  - Existing traits/facts for each user.
  - Phase 1 candidate traits/facts.
- LLM output:
  - Final traits/facts (post-merge).
  - Mapping from final items to Phase 1 candidates (for evidence linkage).
- Decision: If a user has no existing profile, Phase 2 can be skipped for that user (optional optimization).

## Phase 3: Summary Update (Separate)
- Summary update becomes a dedicated step (not in Phase 2).
- It uses the final traits/facts as context.

## Evidence Storage (New Table)
Table: `impression_evidence`
- `group_id`
- `user_id`
- `item_type` (`trait`/`fact`)
- `item_text` (final trait/fact text)
- `message_id`
- `message_text`
- `message_ts`
- `created_at`

Evidence is written by:
1. Taking Phase 1 `evidence_ids`.
2. Applying Phase 2 mapping to resolve final trait/fact text.
3. Inserting evidence rows for final items.

## Dedup & Merge Rules
- LLM decides whether a candidate item:
  - Adds a new item
  - Replaces an existing item
  - Merges into an existing item
- Implementation should de-duplicate identical final items before storing.

## Evidence Aging / Conflict Handling
- Old evidence is retained even if a trait/fact is replaced.
- “Why” queries should show evidence tied to the *current* trait/fact only.
- Optional policy: keep only the most recent evidence per item to avoid noise.

## Evidence Cap
- Default: **3 evidence messages per trait/fact**.
- When inserting, keep the newest N entries per item.

## Summary Evidence
- Do **not** store evidence for summary items.

## LLM Input / Profile Storage Policy
- Do **not** pass `examples` into any LLM prompt.
- Do **not** store `examples` in `profiles` (leave empty).
- Store all evidence exclusively in `impression_evidence`.

## Batch Execution Strategy
- Process per group only.
- Batch by configured “max users per run” (existing group batch logic).
- Messages are capped by `update_msg_threshold` (used as per-run max).

## TODO
- Add a “why” query interface to retrieve evidence for a given trait/fact.

---

# Confidence Plan (Traits/Facts + Evidence)

## Goal
- Attach a final confidence to each trait/fact.
- Store per-evidence contribution (signal) used to compute final confidence.
- Detect “joke/banter” likelihood to down-weight evidence.

## Storage Changes
- Traits/Facts: store `confidence` per item (final value).
- Evidence: store `evidence_confidence` (signal) + `joke_likelihood` per evidence row.
- Evidence rows can contribute to multiple traits/facts (many-to-many).

## Evidence Scoring (LLM-Assisted)
Use LLM to score each evidence item:
- `evidence_confidence`: how strongly this message supports the candidate trait/fact.
- `joke_likelihood`: probability the message is joking / not serious.
- Output should be tied to a specific `(message_id, candidate_item)` pair.

## Final Confidence (Rule/Formula)
Final confidence is computed by deterministic formula from evidence signals.

Suggested formula:
```
signal_i = evidence_confidence_i * (1 - joke_likelihood_i) * source_weight_i * trust_weight_i * consistency_i
final_conf = 1 - Π(1 - clamp(signal_i))
```

Where:
- `source_weight_i`: 1.0 if self-reported, < 1.0 if reported by others.
- `trust_weight_i`: per-speaker trust score (maintained in table).
- `consistency_i`: computed by rule/LLM based on agreement with existing profile.

## Trust Model
- Maintain a per-user trust score (default 0.7).
- Update rules (TBD): penalize on proven contradictions; reward on consistency.

## Joke/Banter Handling
- LLM estimates `joke_likelihood` for each evidence item.
- High joke likelihood strongly down-weights or nullifies the evidence contribution.

## Required Additions
- New table for per-user trust scores.
- Extend evidence storage schema to include:
  - `evidence_confidence`
  - `joke_likelihood`
  - `source_type` (self/other)
- Update pipeline to:
  1) Ask LLM for evidence contribution per candidate item.
  2) Compute final confidence via formula.
  3) Store final confidence on trait/fact.

## TODO
- Decide thresholds for accepting/retiring a trait/fact based on confidence.

## Phase Integration (No New Phases)
- Phase 1 (Candidate Extraction): add `evidence_confidence`, `joke_likelihood`, `source_type` per evidence.
- Phase 2 (Merge/Replace): add `consistency` marker per item (e.g., consistent/neutral/conflicting).
- Phase 3 (Summary): no changes.

### LLM as optional fallback (not default)
- If multiple candidates exist, optionally ask LLM to choose from the candidate list.
- If uncertain, reply asking for clarification.

## Notes on `astrbot_plugin_portrayal`
- AIOCQHTTP only.
- Generates portraits on demand, not persistent.
- Useful for short-term reuse but not enough for long-term storage.
