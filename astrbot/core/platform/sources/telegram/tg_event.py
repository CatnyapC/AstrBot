import asyncio
import os
import re
from typing import Any, cast

import telegramify_markdown
from telegram import ReactionTypeCustomEmoji, ReactionTypeEmoji
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ExtBot

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    At,
    File,
    Image,
    Plain,
    Record,
    Reply,
)
from astrbot.api.platform import AstrBotMessage, MessageType, PlatformMetadata


def _telegram_message_ids(messages) -> list[str]:
    return [
        str(item.message_id) for item in messages if getattr(item, "message_id", None)
    ]


class TelegramPlatformEvent(AstrMessageEvent):
    # Telegram 的最大消息长度限制
    MAX_MESSAGE_LENGTH = 4096

    SPLIT_PATTERNS = {
        "paragraph": re.compile(r"\n\n"),
        "line": re.compile(r"\n"),
        "sentence": re.compile(r"[.!?。！？]"),
        "word": re.compile(r"\s"),
    }

    # 消息类型到 chat action 的映射，用于优先级判断
    ACTION_BY_TYPE: dict[type, str] = {
        Record: ChatAction.UPLOAD_VOICE,
        File: ChatAction.UPLOAD_DOCUMENT,
        Image: ChatAction.UPLOAD_PHOTO,
        Plain: ChatAction.TYPING,
    }

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: ExtBot,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client

    @classmethod
    def _split_message(cls, text: str) -> list[str]:
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return [text]

        chunks = []
        while text:
            if len(text) <= cls.MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break

            split_point = cls.MAX_MESSAGE_LENGTH
            segment = text[: cls.MAX_MESSAGE_LENGTH]

            for _, pattern in cls.SPLIT_PATTERNS.items():
                if matches := list(pattern.finditer(segment)):
                    last_match = matches[-1]
                    split_point = last_match.end()
                    break

            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()

        return chunks

    @classmethod
    async def _send_chat_action(
        cls,
        client: ExtBot,
        chat_id: str,
        action: ChatAction | str,
        message_thread_id: str | None = None,
    ) -> None:
        """发送聊天状态动作"""
        try:
            payload: dict[str, Any] = {"chat_id": chat_id, "action": action}
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id
            await client.send_chat_action(**payload)
        except Exception as e:
            logger.warning(f"[Telegram] 发送 chat action 失败: {e}")

    @classmethod
    def _get_chat_action_for_chain(cls, chain: list[Any]) -> ChatAction | str:
        """根据消息链中的组件类型确定合适的 chat action（按优先级）"""
        for seg_type, action in cls.ACTION_BY_TYPE.items():
            if any(isinstance(seg, seg_type) for seg in chain):
                return action
        return ChatAction.TYPING

    @classmethod
    async def _send_text_chunks(
        cls,
        client: ExtBot,
        text: str,
        payload: dict[str, Any],
        receipt_chain: MessageChain | None = None,
    ) -> list[Any]:
        """Retain each acknowledged chunk before attempting the next one."""
        sent_messages = []
        for chunk in cls._split_message(text):
            try:
                md_text = telegramify_markdown.markdownify(
                    chunk, normalize_whitespace=False
                )
                sent = await client.send_message(
                    text=md_text, parse_mode="MarkdownV2", **cast(Any, payload)
                )
            except BadRequest as e:
                logger.warning(
                    f"MarkdownV2 send failed: {e}. Using plain text instead."
                )
                sent = await client.send_message(text=chunk, **cast(Any, payload))
            sent_messages.append(sent)
            if receipt_chain is not None:
                receipt_chain.record_sent(
                    _telegram_message_ids([sent]),
                    [part for part in receipt_chain.chain if isinstance(part, Reply)]
                    + [Plain(chunk)],
                )
        return sent_messages

    @classmethod
    async def _send_media_with_action(
        cls,
        client: ExtBot,
        upload_action: ChatAction | str,
        send_coro,
        *,
        user_name: str,
        message_thread_id: str | None = None,
        **payload: Any,
    ) -> None:
        """发送媒体时显示 upload action，发送完成后恢复 typing"""
        await cls._send_chat_action(client, user_name, upload_action, message_thread_id)
        await send_coro(**payload)
        await cls._send_chat_action(
            client, user_name, ChatAction.TYPING, message_thread_id
        )

    async def _ensure_typing(
        self,
        user_name: str,
        message_thread_id: str | None = None,
    ) -> None:
        """确保显示 typing 状态"""
        await self._send_chat_action(
            self.client, user_name, ChatAction.TYPING, message_thread_id
        )

    async def send_typing(self) -> None:
        message_thread_id = None
        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            user_name = self.message_obj.group_id
        else:
            user_name = self.get_sender_id()

        if "#" in user_name:
            user_name, message_thread_id = user_name.split("#")

        await self._ensure_typing(user_name, message_thread_id)

    @classmethod
    async def send_with_client(
        cls,
        client: ExtBot,
        message: MessageChain,
        user_name: str,
    ) -> list[Any]:
        image_path = None
        message.sent_receipts.clear()
        sent_messages = []

        has_reply = False
        reply_message_id = None
        at_user_id = None
        for i in message.chain:
            if isinstance(i, Reply):
                has_reply = True
                reply_message_id = i.id
            if isinstance(i, At):
                at_user_id = i.name

        at_flag = False
        message_thread_id = None
        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")

        # 根据消息链确定合适的 chat action 并发送
        action = cls._get_chat_action_for_chain(message.chain)
        await cls._send_chat_action(client, user_name, action, message_thread_id)

        for i in message.chain:
            sent = None
            payload = {
                "chat_id": user_name,
            }
            if has_reply:
                payload["reply_to_message_id"] = str(reply_message_id)
            if message_thread_id:
                payload["message_thread_id"] = message_thread_id

            if isinstance(i, Plain):
                if at_user_id and not at_flag:
                    i.text = f"@{at_user_id} {i.text}"
                    at_flag = True
                sent_messages.extend(
                    await cls._send_text_chunks(client, i.text, payload, message)
                )
            elif isinstance(i, Image):
                image_path = await i.convert_to_file_path()
                sent = await client.send_photo(photo=image_path, **cast(Any, payload))
            elif isinstance(i, File):
                path = await i.get_file()
                name = i.name or os.path.basename(path)
                sent = await client.send_document(
                    document=path, filename=name, **cast(Any, payload)
                )
            elif isinstance(i, Record):
                path = await i.convert_to_file_path()
                sent = await client.send_voice(voice=path, **cast(Any, payload))

            if sent is not None:
                sent_messages.append(sent)
                message.record_sent(
                    _telegram_message_ids([sent]),
                    [part for part in message.chain if isinstance(part, Reply)] + [i],
                )
        return sent_messages

    async def send(self, message: MessageChain) -> None:
        try:
            if self.get_message_type() == MessageType.GROUP_MESSAGE:
                sent_messages = await self.send_with_client(
                    self.client, message, self.message_obj.group_id
                )
            else:
                sent_messages = await self.send_with_client(
                    self.client, message, self.get_sender_id()
                )
        finally:
            self.set_extra(
                "_sent_message_receipts",
                list(self.get_extra("_sent_message_receipts", []) or [])
                + list(message.sent_receipts),
            )
        self.set_extra(
            "_telegram_sent_message_ids", _telegram_message_ids(sent_messages)
        )
        await super().send(message)

    async def react(self, emoji: str | None, big: bool = False) -> None:
        """给原消息添加 Telegram 反应：
        - 普通 emoji：传入 '👍'、'😂' 等
        - 自定义表情：传入其 custom_emoji_id（纯数字字符串）
        - 取消本机器人的反应：传入 None 或空字符串
        """
        try:
            # 解析 chat_id（去掉超级群的 "#<thread_id>" 片段）
            if self.get_message_type() == MessageType.GROUP_MESSAGE:
                chat_id = (self.message_obj.group_id or "").split("#")[0]
            else:
                chat_id = self.get_sender_id()

            message_id = int(self.message_obj.message_id)

            # 组装 reaction 参数（必须是 ReactionType 的列表）
            if not emoji:  # 清空本 bot 的反应
                reaction_param = []  # 空列表表示移除本 bot 的反应
            elif emoji.isdigit():  # 自定义表情：传 custom_emoji_id
                reaction_param = [ReactionTypeCustomEmoji(emoji)]
            else:  # 普通 emoji
                reaction_param = [ReactionTypeEmoji(emoji)]

            await self.client.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=reaction_param,  # 注意是列表
                is_big=big,  # 可选：大动画
            )
        except Exception as e:
            logger.error(f"[Telegram] 添加反应失败: {e}")

    async def send_streaming(self, generator, use_fallback: bool = False):
        message_thread_id = None

        if self.get_message_type() == MessageType.GROUP_MESSAGE:
            user_name = self.message_obj.group_id
        else:
            user_name = self.get_sender_id()

        if "#" in user_name:
            # it's a supergroup chat with message_thread_id
            user_name, message_thread_id = user_name.split("#")
        payload = {
            "chat_id": user_name,
        }
        if message_thread_id:
            payload["reply_to_message_id"] = message_thread_id

        delta = ""
        current_content = ""
        message_id = None
        last_edit_time = 0  # 上次编辑消息的时间
        throttle_interval = 0.6  # 编辑消息的间隔时间 (秒)
        last_chat_action_time = 0  # 上次发送 chat action 的时间
        chat_action_interval = 0.5  # chat action 的节流间隔 (秒)

        # 发送初始 typing 状态
        await self._ensure_typing(user_name, message_thread_id)
        last_chat_action_time = asyncio.get_event_loop().time()

        async for chain in generator:
            if isinstance(chain, MessageChain):
                if chain.type == "break":
                    # 分割符
                    if message_id:
                        try:
                            await self.client.edit_message_text(
                                text=delta,
                                chat_id=payload["chat_id"],
                                message_id=message_id,
                            )
                        except Exception as e:
                            logger.warning(f"编辑消息失败(streaming-break): {e!s}")
                    message_id = None  # 重置消息 ID
                    delta = ""  # 重置 delta
                    continue

                # 处理消息链中的每个组件
                for i in chain.chain:
                    if isinstance(i, Plain):
                        delta += i.text
                    elif isinstance(i, Image):
                        image_path = await i.convert_to_file_path()
                        await self._send_media_with_action(
                            self.client,
                            ChatAction.UPLOAD_PHOTO,
                            self.client.send_photo,
                            user_name=user_name,
                            message_thread_id=message_thread_id,
                            photo=image_path,
                            **cast(Any, payload),
                        )
                        continue
                    elif isinstance(i, File):
                        path = await i.get_file()
                        name = i.name or os.path.basename(path)
                        await self._send_media_with_action(
                            self.client,
                            ChatAction.UPLOAD_DOCUMENT,
                            self.client.send_document,
                            user_name=user_name,
                            message_thread_id=message_thread_id,
                            document=path,
                            filename=name,
                            **cast(Any, payload),
                        )
                        continue
                    elif isinstance(i, Record):
                        path = await i.convert_to_file_path()
                        await self._send_media_with_action(
                            self.client,
                            ChatAction.UPLOAD_VOICE,
                            self.client.send_voice,
                            user_name=user_name,
                            message_thread_id=message_thread_id,
                            voice=path,
                            **cast(Any, payload),
                        )
                        continue
                    else:
                        logger.warning(f"不支持的消息类型: {type(i)}")
                        continue

                # Plain
                if message_id and len(delta) <= self.MAX_MESSAGE_LENGTH:
                    current_time = asyncio.get_event_loop().time()
                    time_since_last_edit = current_time - last_edit_time

                    # 如果距离上次编辑的时间 >= 设定的间隔，等待一段时间
                    if time_since_last_edit >= throttle_interval:
                        # 发送 typing 状态（带节流）
                        current_time = asyncio.get_event_loop().time()
                        if current_time - last_chat_action_time >= chat_action_interval:
                            await self._ensure_typing(user_name, message_thread_id)
                            last_chat_action_time = current_time
                        # 编辑消息
                        try:
                            await self.client.edit_message_text(
                                text=delta,
                                chat_id=payload["chat_id"],
                                message_id=message_id,
                            )
                            current_content = delta
                        except Exception as e:
                            logger.warning(f"编辑消息失败(streaming): {e!s}")
                        last_edit_time = (
                            asyncio.get_event_loop().time()
                        )  # 更新上次编辑的时间
                else:
                    # delta 长度一般不会大于 4096，因此这里直接发送
                    # 发送 typing 状态（带节流）
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_chat_action_time >= chat_action_interval:
                        await self._ensure_typing(user_name, message_thread_id)
                        last_chat_action_time = current_time
                    try:
                        msg = await self.client.send_message(
                            text=delta, **cast(Any, payload)
                        )
                        current_content = delta
                    except Exception as e:
                        logger.warning(f"发送消息失败(streaming): {e!s}")
                    message_id = msg.message_id
                    last_edit_time = (
                        asyncio.get_event_loop().time()
                    )  # 记录初始消息发送时间

        try:
            if delta and current_content != delta:
                try:
                    markdown_text = telegramify_markdown.markdownify(
                        delta,
                        normalize_whitespace=False,
                    )
                    await self.client.edit_message_text(
                        text=markdown_text,
                        chat_id=payload["chat_id"],
                        message_id=message_id,
                        parse_mode="MarkdownV2",
                    )
                except Exception as e:
                    logger.warning(f"Markdown转换失败，使用普通文本: {e!s}")
                    await self.client.edit_message_text(
                        text=delta,
                        chat_id=payload["chat_id"],
                        message_id=message_id,
                    )
        except Exception as e:
            logger.warning(f"编辑消息失败(streaming): {e!s}")

        return await super().send_streaming(generator, use_fallback)
