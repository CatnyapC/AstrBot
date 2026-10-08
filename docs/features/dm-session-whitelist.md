# DM Session Tiers

Private authorization uses only `platform_settings.dm_tiers`, an exact mapping
from `platform-instance:FriendMessage:account-id` to integer tier 0–3. Missing,
invalid, boolean or out-of-range values resolve to tier0 and deny access.
Administrators do not bypass DM tiers. WebChat retains its core exemption;
Foxmi Router still requires an explicit tier for private LLM processing.

Group behavior continues to use `enable_id_white_list`, `id_whitelist` and
`wl_ignore_admin_on_group`. Disabling group restrictions never grants a DM.
Core checks read live configuration. The dynamic tier map survives configuration
integrity checks and reloads; saves remain atomic and publish after disk writes.

The respond stage rechecks permission before ordinary sends, after segmented
waits and during stream consumption. Revocation suppresses pending replies.
Foxmi's shared direct DM send/archive path checks the destination's live tier too.

Thread Router owns rolling message/worker accounting in its existing SQLite
state DB. Core owns admission and reply revocation; it does not add a second
quota ledger. Configuration metadata exposes the tier map with the existing dict
editor. `/dmwl set`, `list` and `usage` use the Router V2 managed pipeline.

The old `dm_whitelist` and `wl_ignore_admin_on_friend` settings are removed.
Before loading the new config, use Router's one-time `scripts/migrate_dm_tiers.py`
on the default/profile JSON files. Explicit old entries become tier1; implicit
administrator access is not migrated. The script keeps an original-file backup.

See `data/plugins/astrbot_plugin_thread_router/docs/intent_tools/dm_whitelist_admin_managed_tool.md`
for the limits, worker scope and operational commands.
