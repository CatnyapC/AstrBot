# DM Session Whitelist

When `platform_settings.enable_id_white_list=true`, private messages require
their full `platform-instance:FriendMessage:account-id` in the effective
configuration's `id_whitelist`. An empty list denies private messages.
Bare account IDs and entries belonging to another platform instance do not
authorize a DM. Group behavior is unchanged: an empty list permits groups,
and group IDs or full group session IDs can authorize groups.

Existing exemptions remain explicit: WebChat is exempt, administrators can
bypass according to `wl_ignore_admin_on_friend` / `wl_ignore_admin_on_group`,
and disabling `enable_id_white_list` disables this gate. Keep the gate enabled
for a restricted DM deployment. Removing an administrator from the allowlist
does not revoke an enabled administrator exemption.

The whitelist stage reads the current configuration for every event rather
than caching a list at initialization. Updating `AstrBotConfig.save_config`
therefore takes effect without restarting the scheduler. Saves write a
same-directory temporary file, flush it, replace the destination atomically,
then update the in-memory configuration. Failed writes leave the previous
configuration and live permissions intact.

The respond stage checks DM permissions again immediately before ordinary
sends, after segmented-send waits, and while consuming streaming results.
Revocation suppresses pending pipeline replies; already sent content cannot
be withdrawn. Direct platform sends that bypass the pipeline are outside
this gate and must check permission themselves.

Foxmi's optional `/dmwl` command and V2 managed plain tool maintain this
existing list. They do not introduce another access database. See the Thread
Router plugin's `docs/intent_tools/dm_whitelist_admin_managed_tool.md` for
administrator usage and the distinction between DM access and memory access.
