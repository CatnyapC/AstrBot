# Parser Whitelist Admin Bypass

`astrbot_plugin_parser` keeps its per-group parser whitelist JSON behavior for ordinary users. When the whitelist is configured, non-admin users must still appear under the current group id, or under the legacy global `*` entry.

AstrBot administrators from the runtime `admins_id` config bypass the parser whitelist in every group. They do not need to be duplicated into each group-specific whitelist entry.

Malformed or empty whitelist JSON keeps the existing parser behavior: it falls back to an empty runtime whitelist, which means parser whitelist filtering does not restrict users.
