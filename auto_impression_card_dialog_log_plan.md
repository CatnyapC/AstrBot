# Dialog Log + Summary Cursor Plan

## Goal
Stop losing information when `message_queue` is cleared by keeping a full dialog log as the source of truth, and summarizing via a cursor.

## Data Model
### New table: `dialog_log`
- `id` (autoincrement)
- `group_id`
- `user_id`
- `message`
- `ts`
- Index on `(group_id, id)`

### New table: `summary_cursor`
- `group_id`
- `last_summarized_id`
- `updated_at`

## Write Path
- Every incoming message is appended to `dialog_log`.
- `message_queue` becomes a **temporary trigger buffer** only.

## Summary Flow
1) Read `last_summarized_id` for the group.
2) Fetch `dialog_log` rows where `id > last_summarized_id` (limit by config).
3) Run summarization / impression updates on these rows.
4) On success, update `last_summarized_id` to the newest processed id.

## Archive Policy
- If `dialog_log` per group exceeds `MAX_LOG_SIZE` (e.g., 5000):
  - Export old rows to archive file (or archive table)
  - Clear `dialog_log`
  - Reset `last_summarized_id = 0`

## Config Additions
- `dialog_log_max_rows` (default 5000)
- `dialog_log_batch_size` (messages per summary)

## Benefits
- No data loss from queue clearing
- Deterministic summary window
- Easy to resume after restart

## TODO
- Decide archive storage format (table vs file)
- Add admin command to export/clear logs manually
