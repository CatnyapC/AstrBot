import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiocqhttp.exceptions import ActionFailed

from astrbot.api.event import MessageChain
from astrbot.core.message.components import File, Plain, Reply
from astrbot.core.pipeline.respond.stage import RespondStage
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform import Platform
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot.core.platform.sources.telegram.tg_event import TelegramPlatformEvent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,state",
    [
        (
            ActionFailed(
                {
                    "status": "failed",
                    "retcode": 200,
                    "wording": "EventChecker Failed: result=4",
                }
            ),
            "failed",
        ),
        (
            ActionFailed(
                {"status": "failed", "retcode": 200, "wording": "Timeout: sendMsg"}
            ),
            "unknown",
        ),
        (TimeoutError(), "unknown"),
    ],
)
async def test_onebot_failure_records_actual_outcome_without_resending(error, state):
    bot = AsyncMock()
    bot.send_group_msg.side_effect = error
    chain = MessageChain([Plain("attempted")])
    with pytest.raises(type(error)):
        await AiocqhttpMessageEvent.send_message(
            bot, chain, is_group=True, session_id="42"
        )
    assert bot.send_group_msg.await_count == 1
    receipt = chain.sent_receipts[0]
    assert receipt.delivery_state == state
    assert receipt.raw_ids == ()
    assert receipt.chain[0].text == "attempted"
    assert receipt.error


@pytest.mark.asyncio
async def test_onebot_conversion_failure_is_known_unsent(monkeypatch):
    monkeypatch.setattr(
        AiocqhttpMessageEvent,
        "_parse_onebot_json",
        AsyncMock(side_effect=ValueError("invalid image")),
    )
    bot = AsyncMock()
    chain = MessageChain([Plain("attempted")])
    with pytest.raises(ValueError):
        await AiocqhttpMessageEvent.send_message(
            bot, chain, is_group=True, session_id="42"
        )
    bot.send_group_msg.assert_not_awaited()
    assert chain.sent_receipts[0].delivery_state == "failed"


@pytest.mark.asyncio
async def test_failed_main_reply_reaches_after_send_hook(monkeypatch):
    message = AstrBotMessage()
    message.type = MessageType.GROUP_MESSAGE
    message.group_id = "42"
    message.self_id = "bot"
    message.sender = MessageMember(user_id="peer", nickname="peer")
    message.message = []
    message.raw_message = {}
    bot = AsyncMock()
    bot.send_group_msg.side_effect = ActionFailed(
        {"status": "failed", "retcode": 200, "wording": "rejected"}
    )
    event = AiocqhttpMessageEvent(
        "", message, PlatformMetadata("aiocqhttp", "QQ", "qq"), "42", bot
    )
    event.set_result(event.plain_result("未送达正文"))
    stage = RespondStage()
    stage.config = {}
    stage.platform_settings = {}
    monkeypatch.setattr(stage, "is_seg_reply_required", lambda event: False)
    received = []

    async def hook(event, kind):
        received.extend(event.get_extra("_sent_message_receipts", []))
        return False

    monkeypatch.setitem(RespondStage.process.__globals__, "call_event_hook", hook)
    await stage.process(event)
    assert len(received) == 1
    assert received[0].delivery_state == "failed"
    assert received[0].chain[0].text == "未送达正文"
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_onebot_session_send_retains_ids_and_receipts(monkeypatch):
    adapter = AiocqhttpAdapter.__new__(AiocqhttpAdapter)
    adapter.bot = AsyncMock()
    adapter.bot.send_private_msg.return_value = {"message_id": 123}
    monkeypatch.setattr(Platform, "send_by_session", AsyncMock())
    chain = MessageChain([Plain("hello")])
    await adapter.send_by_session(
        MessageSession("qq", MessageType.FRIEND_MESSAGE, "42"), chain
    )
    assert chain._onebot_sent_message_ids == ["123"]
    assert chain.sent_receipts[0].raw_ids == ("123",)
    assert chain.sent_receipts[0].chain[0].text == "hello"
    chain.chain[0].text = "changed later"
    assert chain.sent_receipts[0].chain[0].text == "hello"
    assert chain.derive().sent_receipts == []


@pytest.mark.asyncio
async def test_onebot_partial_send_and_reuse_clear_stale_receipts(monkeypatch):
    bot = AsyncMock()
    bot.send_private_msg.side_effect = [
        {"message_id": 1},
        RuntimeError("second failed"),
    ]
    chain = MessageChain([Plain("first"), File(name="file", file="/unused")])
    monkeypatch.setattr(
        AiocqhttpMessageEvent,
        "_from_segment_to_dict",
        AsyncMock(return_value={"type": "file", "data": {}}),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    with pytest.raises(RuntimeError, match="second failed"):
        await AiocqhttpMessageEvent.send_message(bot, chain, session_id="42")
    assert chain._onebot_sent_message_ids == ["1"]
    assert len(chain.sent_receipts) == 2
    assert chain.sent_receipts[0].chain[0].text == "first"
    assert chain.sent_receipts[1].delivery_state == "unknown"
    assert chain.sent_receipts[1].chain[0].name == "file"
    bot.send_private_msg.side_effect = RuntimeError("first failed")
    with pytest.raises(RuntimeError, match="first failed"):
        await AiocqhttpMessageEvent.send_message(bot, chain, session_id="42")
    assert len(chain.sent_receipts) == 1
    assert chain.sent_receipts[0].raw_ids == ()
    assert chain.sent_receipts[0].error == "first failed"
    assert chain._onebot_sent_message_ids == []


@pytest.mark.asyncio
async def test_telegram_chunk_failure_keeps_only_acknowledged_text(monkeypatch):
    client = AsyncMock()
    client.send_message.side_effect = [
        SimpleNamespace(message_id=11),
        RuntimeError("later failed"),
    ]
    monkeypatch.setattr(
        TelegramPlatformEvent, "_split_message", lambda text: ["part one", "part two"]
    )
    monkeypatch.setattr(TelegramPlatformEvent, "_send_chat_action", AsyncMock())
    chain = MessageChain([Reply(id="9"), Plain("full text")])
    with pytest.raises(RuntimeError, match="later failed"):
        await TelegramPlatformEvent.send_with_client(client, chain, "42")
    assert len(chain.sent_receipts) == 1
    receipt = chain.sent_receipts[0]
    assert receipt.raw_ids == ("11",)
    assert receipt.chain[0].id == "9"
    assert receipt.chain[1].text == "part one"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["aiocqhttp", "telegram"])
async def test_segmented_reply_collects_all_receipts_and_resets_each_round(
    platform, monkeypatch
):
    message = AstrBotMessage()
    message.type = MessageType.FRIEND_MESSAGE
    message.self_id = "bot"
    message.sender = MessageMember(user_id="42", nickname="peer")
    message.message = []
    message.raw_message = {}
    client = AsyncMock()
    meta = PlatformMetadata(platform, platform, "instance")
    if platform == "aiocqhttp":
        client.send_private_msg.side_effect = [
            {"message_id": 1},
            {"message_id": 2},
            {"message_id": 3},
        ]
        event = AiocqhttpMessageEvent("", message, meta, "42", client)
    else:
        client.send_message.side_effect = [
            SimpleNamespace(message_id=value) for value in (1, 2, 3)
        ]
        event = TelegramPlatformEvent("", message, meta, "42", client)
        monkeypatch.setattr(TelegramPlatformEvent, "_send_chat_action", AsyncMock())
    stage = RespondStage()
    stage.config = {
        "platform_settings": {
            "enable_id_white_list": True,
            "dm_tiers": {event.unified_msg_origin: 1},
        }
    }
    stage.platform_settings = {}
    monkeypatch.setattr(stage, "is_seg_reply_required", lambda event: True)
    monkeypatch.setattr(stage, "_calc_comp_interval", AsyncMock(return_value=0))
    rounds = []

    async def hook(event, kind):
        rounds.append([r.raw_ids for r in event.get_extra("_sent_message_receipts")])
        return False

    monkeypatch.setitem(RespondStage.process.__globals__, "call_event_hook", hook)
    event.set_result(event.chain_result([Plain("one"), Plain("two")]))
    await stage.process(event)
    event.set_result(event.plain_result("three"))
    await stage.process(event)
    assert rounds == [[("1",), ("2",)], [("3",)]]
