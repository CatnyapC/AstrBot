# Humiao Online Test Sender

Inbox manifests send live test messages from the configured humiao sender bot.

## Platform Selection

`Basic.platform_type` controls the sender adapter:

- `aiocqhttp`: existing QQ/OneBot path. Manifests use numeric group ids and optional `message.at_user_ids`.
- `telegram`: Telegram path. Set `Basic.humiao_platform_id` to the Telegram sender adapter id, and set `Basic.allowed_group_ids` to the allowed Telegram chat ids, for example `-5163620321`.
- `auto`: resolve the sender by `Basic.humiao_platform_id` across supported adapters.

`Basic.humiao_platform_id` is the sender platform id. It must match the configured AstrBot adapter id for the bot that sends test messages.

For Telegram forum topics, put the topic id in the manifest group id as `chat_id#message_thread_id`, for example `-5163620321#123`.

For Telegram reply smokes, set `message.reply_to_message_id` to the Telegram message id being replied to. The sender passes it to the Bot API as `reply_to_message_id`.

Telegram `message.at_user_ids` is accepted for schema compatibility and currently ignored.
