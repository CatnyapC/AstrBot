import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (  # noqa: E402
    PLATFORM_AIOCQHTTP,
    PLATFORM_TELEGRAM,
    HumiaoOnlineTestSender,
    PluginConfig,
    _telegram_group_parts,
)


def build_sender(config: PluginConfig) -> HumiaoOnlineTestSender:
    sender = object.__new__(HumiaoOnlineTestSender)
    sender.config = config
    sender._warned_missing_platform = False
    return sender


class RaisingIdentityClient:
    def __init__(self):
        self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=999))

    @property
    def id(self):
        raise RuntimeError("ExtBot is not properly initialized")

    @property
    def username(self):
        raise RuntimeError("ExtBot is not properly initialized")

    @property
    def first_name(self):
        raise RuntimeError("ExtBot is not properly initialized")


def test_aiocqhttp_path_keeps_onebot_send_group_msg_payload():
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_AIOCQHTTP,
            allowed_group_ids=("499574167",),
        )
    )
    bot = SimpleNamespace(call_action=AsyncMock(return_value={"message_id": 123}))
    adapter = SimpleNamespace(bot=bot)

    report = asyncio.run(
        sender._send_case(
            adapter,
            {
                "case_id": "qq-case",
                "group_id": "499574167",
                "message": {"text": "hello", "at_user_ids": ["10001"]},
            },
            default_group_id="",
            default_delay_ms=0,
            adapter_self_id="qq-bot",
            adapter_id="fox_miao_bot",
            platform_type=PLATFORM_AIOCQHTTP,
        )
    )

    bot.call_action.assert_awaited_once()
    args, kwargs = bot.call_action.await_args
    assert args == ("send_group_msg",)
    assert kwargs["group_id"] == 499574167
    assert kwargs["message"] == [
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": " "}},
        {"type": "text", "data": {"text": "hello"}},
    ]
    assert report["status"] == "sent"
    assert report["raw_message_id"] == "123"


def test_resolve_telegram_adapter_by_config_id():
    telegram_adapter = SimpleNamespace(
        config={"id": "fox_miao_bot"},
        meta=lambda: SimpleNamespace(name="telegram", id="fox_miao_bot"),
    )
    other_adapter = SimpleNamespace(
        config={"id": "other"},
        meta=lambda: SimpleNamespace(name="telegram", id="other"),
    )
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_TELEGRAM,
            humiao_platform_id="fox_miao_bot",
        )
    )
    sender.context = SimpleNamespace(
        platform_manager=SimpleNamespace(
            get_insts=lambda: [other_adapter, telegram_adapter]
        )
    )

    assert sender._resolve_adapter() is telegram_adapter


def test_negative_telegram_group_id_allowed_and_sent():
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_TELEGRAM,
            allowed_group_ids=("-5163620321",),
        )
    )
    client = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=456))
    )
    adapter = SimpleNamespace(client=client)

    report = asyncio.run(
        sender._send_case(
            adapter,
            {
                "case_id": "tg-case",
                "group_id": "-5163620321",
                "message": {"text": "telegram hello"},
            },
            default_group_id="",
            default_delay_ms=0,
            adapter_self_id="tg-bot",
            adapter_id="fox_miao_bot",
            platform_type=PLATFORM_TELEGRAM,
        )
    )

    client.send_message.assert_awaited_once_with(
        chat_id=-5163620321,
        text="telegram hello",
    )
    assert report["status"] == "sent"
    assert report["telegram_chat_id"] == -5163620321
    assert report["telegram_message_id"] == "456"


def test_telegram_topic_suffix_becomes_message_thread_id():
    assert _telegram_group_parts("-5163620321#777") == (-5163620321, 777, None)
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_TELEGRAM,
            allowed_group_ids=("-5163620321",),
        )
    )
    client = SimpleNamespace(send_message=AsyncMock(return_value={"message_id": 789}))
    adapter = SimpleNamespace(client=client)

    report = asyncio.run(
        sender._send_case(
            adapter,
            {
                "case_id": "tg-topic-case",
                "group_id": "-5163620321#777",
                "message": {"text": "topic hello"},
            },
            default_group_id="",
            default_delay_ms=0,
            adapter_self_id="tg-bot",
            adapter_id="fox_miao_bot",
            platform_type=PLATFORM_TELEGRAM,
        )
    )

    client.send_message.assert_awaited_once_with(
        chat_id=-5163620321,
        text="topic hello",
        message_thread_id=777,
    )
    assert report["status"] == "sent"
    assert report["telegram_message_thread_id"] == 777
    assert report["telegram_send_payload"] == {
        "chat_id": -5163620321,
        "text": "topic hello",
        "message_thread_id": 777,
    }


def test_telegram_reply_to_message_id_passes_to_send_payload():
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_TELEGRAM,
            allowed_group_ids=("-5163620321",),
        )
    )
    client = SimpleNamespace(send_message=AsyncMock(return_value={"message_id": 790}))
    adapter = SimpleNamespace(client=client)

    report = asyncio.run(
        sender._send_case(
            adapter,
            {
                "case_id": "tg-reply-case",
                "group_id": "-5163620321#777",
                "message": {
                    "text": "reply hello",
                    "reply_to_message_id": "750",
                },
            },
            default_group_id="",
            default_delay_ms=0,
            adapter_self_id="tg-bot",
            adapter_id="fox_miao_bot",
            platform_type=PLATFORM_TELEGRAM,
        )
    )

    client.send_message.assert_awaited_once_with(
        chat_id=-5163620321,
        text="reply hello",
        message_thread_id=777,
        reply_to_message_id=750,
    )
    assert report["status"] == "sent"
    assert report["telegram_message_thread_id"] == 777
    assert report["telegram_reply_to_message_id"] == 750
    assert report["message"]["reply_to_message_id"] == 750
    assert report["telegram_send_payload"] == {
        "chat_id": -5163620321,
        "text": "reply hello",
        "message_thread_id": 777,
        "reply_to_message_id": 750,
    }


def test_manifest_send_survives_telegram_identity_property_error(tmp_path):
    sender = build_sender(
        PluginConfig(
            platform_type=PLATFORM_TELEGRAM,
            humiao_platform_id="fox_miao_bot",
            allowed_group_ids=("-5163620321",),
        )
    )
    sender._report_dir = tmp_path / "reports"
    sender._processed_dir = tmp_path / "processed"
    sender._report_dir.mkdir()
    sender._processed_dir.mkdir()
    client = RaisingIdentityClient()
    adapter = SimpleNamespace(
        config={"id": "fox_miao_bot"},
        client=client,
        client_self_id="telegram-adapter-self-id",
        meta=lambda: SimpleNamespace(name="telegram", id="fox_miao_bot"),
    )
    sender.context = SimpleNamespace(
        platform_manager=SimpleNamespace(get_insts=lambda: [adapter])
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "default_group_id": "-5163620321",
                "send_interval_ms": 0,
                "cases": [
                    {
                        "case_id": "identity-error",
                        "message": {"text": "still sends"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    asyncio.run(sender._process_manifest(manifest_path))

    report = json.loads((sender._report_dir / "manifest.json").read_text())
    client.send_message.assert_awaited_once_with(
        chat_id=-5163620321,
        text="still sends",
    )
    assert report["status"] == "completed"
    assert "error" not in report
    assert "sender_bot_id" not in report
    assert report["adapter_id"] == "fox_miao_bot"
    assert report["cases"][0]["status"] == "sent"
    assert report["cases"][0]["telegram_message_id"] == "999"
