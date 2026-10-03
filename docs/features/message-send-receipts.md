# Message Send Receipts

`MessageChain.sent_receipts` holds acknowledgments from the current send attempt.
Each `SentMessageReceipt` contains platform `raw_ids`, a deep-copied component
snapshot, and `sent_at`. It is transport metadata, not an Archive ID or a promise
of delivery to a human. `derive()` starts without receipts.

OneBot records every acknowledged dispatch, including separate files/forwards.
Telegram records every acknowledged text chunk and media message. If a later
dispatch fails, earlier receipts remain available. Session sends retain receipts
on the supplied chain even when the platform method returns no IDs.

Event sends also accumulate receipts in `_sent_message_receipts`.
`RespondStage` clears that collection at the start of a response, so segmented
non-streaming replies reach the after-send hook with all acknowledged parts and
no receipts from an earlier response. The Archive DM hook consumes this list,
including when the response chain was emptied by separate-component sending.

Consumers must distinguish send failure, unknown delivery, partial send, and
archive failure. No ID means no confirmed archive row. An archive failure after
a successful platform send is not permission to resend. Receipt storage is
in-memory; this is not a durable outbox or an exactly-once guarantee.

Coverage is currently OneBot and Telegram non-streaming dispatch. Other adapters
do not yet populate this contract. Streaming paths bypass the normal after-send
hook and need separate integration before DM rollout; do not infer coverage from
the presence of receipts alone.

Validation (mock transport; run from the repository root):

```bash
uv run pytest tests/unit/test_send_receipts.py tests/unit/test_aiocqhttp_poke.py -q
```

Tests cover session IDs, snapshots, partial dispatch, stale receipt clearing,
Telegram chunk failures, and segmented replies across successive response rounds.
