import asyncio
import re
from collections.abc import AsyncGenerator

from aiocqhttp import CQHttp, Event

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    BaseMessageComponent,
    File,
    Image,
    Node,
    Nodes,
    Plain,
    Record,
    Video,
)
from astrbot.api.platform import Group, MessageMember


class AiocqhttpMessageEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str,
        message_obj,
        platform_meta,
        session_id,
        bot: CQHttp,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.bot = bot

    @staticmethod
    async def _from_segment_to_dict(segment: BaseMessageComponent) -> dict:
        """修复部分字段"""
        if isinstance(segment, Image | Record):
            # For Image and Record segments, we convert them to base64
            bs64 = await segment.convert_to_base64()
            return {
                "type": segment.type.lower(),
                "data": {
                    "file": f"base64://{bs64}",
                },
            }
        if isinstance(segment, File):
            # For File segments, we need to handle the file differently
            d = await segment.to_dict()
            return d
        if isinstance(segment, Video):
            d = await segment.to_dict()
            return d
        # For other segments, we simply convert them to a dict by calling toDict
        return segment.toDict()

    @staticmethod
    async def _parse_onebot_json(message_chain: MessageChain):
        """解析成 OneBot json 格式"""
        ret = []
        for segment in message_chain.chain:
            if isinstance(segment, Plain):
                if not segment.text.strip():
                    continue
            d = await AiocqhttpMessageEvent._from_segment_to_dict(segment)
            ret.append(d)
        return ret

    @staticmethod
    def _extract_sent_message_ids(result) -> list[str]:
        """Extract IDs only from acknowledged OneBot responses."""
        if not isinstance(result, dict):
            return []
        data = result.get("data", result)
        if not isinstance(data, dict):
            return []
        raw_id = data.get("message_id")
        return [str(raw_id)] if isinstance(raw_id, (str, int)) and raw_id else []

    @classmethod
    async def _dispatch_send(
        cls,
        bot: CQHttp,
        event: Event | None,
        is_group: bool,
        session_id: str | None,
        messages: list[dict],
    ):
        # session_id 必须是纯数字字符串
        session_id_int = (
            int(session_id) if session_id and session_id.isdigit() else None
        )

        if is_group and isinstance(session_id_int, int):
            return await bot.send_group_msg(group_id=session_id_int, message=messages)
        elif not is_group and isinstance(session_id_int, int):
            return await bot.send_private_msg(user_id=session_id_int, message=messages)
        elif isinstance(event, Event):  # 最后兜底
            return await bot.send(event=event, message=messages)
        else:
            raise ValueError(
                f"无法发送消息：缺少有效的数字 session_id({session_id}) 或 event({event})",
            )

    @classmethod
    async def send_message(
        cls,
        bot: CQHttp,
        message_chain: MessageChain,
        event: Event | None = None,
        is_group: bool = False,
        session_id: str | None = None,
    ) -> list[str]:
        """发送消息至 QQ 协议端（aiocqhttp）。

        Args:
            bot (CQHttp): aiocqhttp 机器人实例
            message_chain (MessageChain): 要发送的消息链
            event (Event | None, optional): aiocqhttp 事件对象.
            is_group (bool, optional): 是否为群消息.
            session_id (str | None, optional): 会话 ID（群号或 QQ 号

        """
        message_chain.sent_receipts.clear()
        sent_message_ids: list[str] = []
        setattr(message_chain, "_onebot_sent_message_ids", sent_message_ids)

        def record_result(result, components):
            ids = cls._extract_sent_message_ids(result)
            message_chain.record_sent(ids, components)
            sent_message_ids.extend(ids)

        # 转发消息、文件消息不能和普通消息混在一起发送
        send_one_by_one = any(
            isinstance(seg, Node | Nodes | File) for seg in message_chain.chain
        )
        if not send_one_by_one:
            ret = await cls._parse_onebot_json(message_chain)
            if not ret:
                return sent_message_ids
            send_result = await cls._dispatch_send(
                bot, event, is_group, session_id, ret
            )
            record_result(send_result, message_chain.chain)
            return sent_message_ids
        for seg in message_chain.chain:
            if isinstance(seg, Node | Nodes):
                # 合并转发消息
                if isinstance(seg, Node):
                    nodes = Nodes([seg])
                    seg = nodes

                payload = await seg.to_dict()

                if is_group:
                    payload["group_id"] = session_id
                    send_result = await bot.call_action(
                        "send_group_forward_msg", **payload
                    )
                else:
                    payload["user_id"] = session_id
                    send_result = await bot.call_action(
                        "send_private_forward_msg", **payload
                    )
                record_result(send_result, [seg])
            elif isinstance(seg, File):
                d = await cls._from_segment_to_dict(seg)
                send_result = await cls._dispatch_send(
                    bot, event, is_group, session_id, [d]
                )
                record_result(send_result, [seg])
            else:
                messages = await cls._parse_onebot_json(MessageChain([seg]))
                if not messages:
                    continue
                send_result = await cls._dispatch_send(
                    bot, event, is_group, session_id, messages
                )
                record_result(send_result, [seg])
                await asyncio.sleep(0.5)

        return sent_message_ids

    async def send(self, message: MessageChain) -> None:
        """Send and retain acknowledged receipts even if a later dispatch fails."""
        event = getattr(self.message_obj, "raw_message", None)
        is_group = bool(self.get_group_id())
        session_id = self.get_group_id() if is_group else self.get_sender_id()
        try:
            sent_message_ids = await self.send_message(
                bot=self.bot,
                message_chain=message,
                event=event,
                is_group=is_group,
                session_id=session_id,
            )
        finally:
            self.set_extra(
                "_sent_message_receipts",
                list(self.get_extra("_sent_message_receipts", []) or [])
                + list(message.sent_receipts),
            )
        if sent_message_ids:
            self.set_extra("_onebot_sent_message_ids", sent_message_ids)
        await super().send(message)

    async def send_streaming(
        self,
        generator: AsyncGenerator,
        use_fallback: bool = False,
    ):
        if not use_fallback:
            buffer = None
            async for chain in generator:
                if not buffer:
                    buffer = chain
                else:
                    buffer.chain.extend(chain.chain)
            if not buffer:
                return None
            buffer.squash_plain()
            await self.send(buffer)
            return await super().send_streaming(generator, use_fallback)

        buffer = ""
        pattern = re.compile(r"[^。？！~…]+[。？！~…]+")

        async for chain in generator:
            if isinstance(chain, MessageChain):
                for comp in chain.chain:
                    if isinstance(comp, Plain):
                        buffer += comp.text
                        if any(p in buffer for p in "。？！~…"):
                            buffer = await self.process_buffer(buffer, pattern)
                    else:
                        await self.send(MessageChain(chain=[comp]))
                        await asyncio.sleep(1.5)  # 限速

        if buffer.strip():
            await self.send(MessageChain([Plain(buffer)]))
        return await super().send_streaming(generator, use_fallback)

    async def get_group(self, group_id=None, **kwargs):
        if isinstance(group_id, str) and group_id.isdigit():
            group_id = int(group_id)
        elif self.get_group_id():
            group_id = int(self.get_group_id())
        else:
            return None

        info: dict = await self.bot.call_action(
            "get_group_info",
            group_id=group_id,
        )

        members: list[dict] = await self.bot.call_action(
            "get_group_member_list",
            group_id=group_id,
        )

        owner_id = None
        admin_ids = []
        for member in members:
            if member["role"] == "owner":
                owner_id = member["user_id"]
            if member["role"] == "admin":
                admin_ids.append(member["user_id"])

        group = Group(
            group_id=str(group_id),
            group_name=info.get("group_name"),
            group_avatar="",
            group_admins=admin_ids,
            group_owner=str(owner_id),
            members=[
                MessageMember(
                    user_id=member["user_id"],
                    nickname=member.get("nickname") or member.get("card"),
                )
                for member in members
            ],
        )

        return group
