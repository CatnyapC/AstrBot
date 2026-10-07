from collections.abc import AsyncGenerator

from astrbot.core import logger
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.message_type import MessageType

from ..context import PipelineContext
from ..stage import Stage, register_stage


def is_event_whitelisted(event: AstrMessageEvent, settings: dict) -> bool:
    """Keep DM permissions independent of the group whitelist and its switch."""
    if event.get_platform_name() == "webchat":
        return True
    private = event.get_message_type() == MessageType.FRIEND_MESSAGE
    if not private and not settings.get("enable_id_white_list", True):
        return True
    bypass = "wl_ignore_admin_on_friend" if private else "wl_ignore_admin_on_group"
    if event.is_admin() and settings.get(bypass, False):
        return True
    entries = settings.get("dm_whitelist" if private else "id_whitelist", [])
    if not isinstance(entries, list):
        return False
    whitelist = {str(value).strip() for value in entries if str(value).strip()}
    if not whitelist:
        return not private
    return event.unified_msg_origin in whitelist or (
        not private and str(event.get_group_id()).strip() in whitelist
    )


@register_stage
class WhitelistCheckStage(Stage):
    """检查是否在群聊/私聊白名单"""

    async def initialize(self, ctx: PipelineContext) -> None:
        self.config = ctx.astrbot_config

    async def process(
        self,
        event: AstrMessageEvent,
    ) -> None | AsyncGenerator[None, None]:
        settings = self.config.get("platform_settings", {})
        if is_event_whitelisted(event, settings):
            return
        if settings.get("id_whitelist_log", True):
            logger.info(
                "会话 ID %s 不在会话白名单中，已终止事件传播。",
                event.unified_msg_origin,
            )
        event.stop_event()
