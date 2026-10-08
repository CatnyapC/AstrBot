import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def setup_gate(entries=(), *, private=True, admin=False):
    from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage
    from astrbot.core.platform.message_type import MessageType

    config = {
        "platform_settings": {
            "enable_id_white_list": True,
            "id_whitelist": [] if private else list(entries),
            "dm_tiers": dict.fromkeys(entries, 1) if private else {},
            "wl_ignore_admin_on_group": True,
            "id_whitelist_log": False,
        }
    }
    stopped = []
    event = SimpleNamespace(
        unified_msg_origin="onebot:FriendMessage:42"
        if private
        else "onebot:GroupMessage:123",
        get_platform_name=lambda: "aiocqhttp",
        get_message_type=lambda: (
            MessageType.FRIEND_MESSAGE if private else MessageType.GROUP_MESSAGE
        ),
        get_group_id=lambda: "" if private else "123",
        is_admin=lambda: admin,
        stop_event=lambda: stopped.append(True),
    )
    stage = WhitelistCheckStage()
    asyncio.run(stage.initialize(SimpleNamespace(astrbot_config=config)))
    return config, event, stage, stopped


@pytest.mark.parametrize(
    "private,admin,entries,blocked",
    [
        (True, False, [], True),
        (True, False, ["onebot:FriendMessage:42"], False),
        (True, False, ["other:FriendMessage:42"], True),
        (True, False, ["42"], True),
        (True, False, [" "], True),
        (True, True, [], True),
        (False, False, [], False),
        (False, False, ["123"], False),
        (False, False, ["onebot:GroupMessage:123"], False),
        (False, False, ["456"], True),
    ],
)
def test_whitelist_boundaries(private, admin, entries, blocked):
    _, event, stage, stopped = setup_gate(entries, private=private, admin=admin)
    asyncio.run(stage.process(event))
    assert bool(stopped) == blocked


def test_gate_reads_live_config_and_retains_explicit_exemptions():
    config, event, stage, stopped = setup_gate()
    config["platform_settings"] = {
        **config["platform_settings"],
        "dm_tiers": {event.unified_msg_origin: 1},
    }
    asyncio.run(stage.process(event))
    assert not stopped
    config["platform_settings"]["dm_tiers"] = {}
    asyncio.run(stage.process(event))
    assert stopped
    stopped.clear()
    config["platform_settings"]["enable_id_white_list"] = False
    asyncio.run(stage.process(event))
    assert stopped
    stopped.clear()
    event.get_platform_name = lambda: "webchat"
    asyncio.run(stage.process(event))
    assert not stopped


def test_admin_bypass_cannot_override_tier0():
    config, event, stage, stopped = setup_gate(admin=True)
    config["platform_settings"]["wl_ignore_admin_on_friend"] = False
    asyncio.run(stage.process(event))
    assert stopped


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("group_entries", [[], ["123"], ["456"]])
def test_dm_grants_and_revocation_do_not_change_group_access(enabled, group_entries):
    from astrbot.core.pipeline.whitelist_check.stage import is_event_whitelisted

    config, group, _, _ = setup_gate(group_entries, private=False)
    _, dm, _, _ = setup_gate()
    settings = config["platform_settings"]
    settings["enable_id_white_list"] = enabled
    expected_group = not enabled or not group_entries or "123" in group_entries
    assert is_event_whitelisted(group, settings) == expected_group
    assert not is_event_whitelisted(dm, settings)
    settings["dm_tiers"] = {dm.unified_msg_origin: 1}
    assert is_event_whitelisted(dm, settings)
    assert is_event_whitelisted(group, settings) == expected_group
    settings["dm_tiers"] = {}
    assert not is_event_whitelisted(dm, settings)
    assert is_event_whitelisted(group, settings) == expected_group


@pytest.mark.parametrize("entries", [None, {}, "onebot:FriendMessage:42", []])
def test_dm_gate_fails_closed_and_never_uses_group_list(entries):
    config, event, stage, stopped = setup_gate()
    settings = config["platform_settings"]
    settings["enable_id_white_list"] = False
    settings["id_whitelist"] = [event.unified_msg_origin]
    settings["dm_tiers"] = entries
    asyncio.run(stage.process(event))
    assert stopped


def test_atomic_config_failure_preserves_memory_and_disk(tmp_path, monkeypatch):
    from astrbot.core.config.astrbot_config import AstrBotConfig

    config = AstrBotConfig(
        str(tmp_path / "config.json"),
        default_config={"platform_settings": {"dm_tiers": {}}},
    )
    before = copy.deepcopy(dict(config))
    disk = Path(config.config_path).read_bytes()
    replace = Path.replace

    def fail(_self, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        config.save_config(
            {"platform_settings": {"dm_tiers": {"onebot:FriendMessage:42": 1}}}
        )
    assert dict(config) == before and Path(config.config_path).read_bytes() == disk
    assert list(tmp_path.iterdir()) == [Path(config.config_path)]
    monkeypatch.setattr(Path, "replace", replace)
    config.save_config(
        {"platform_settings": {"dm_tiers": {"onebot:FriendMessage:42": 1}}}
    )
    assert json.loads(Path(config.config_path).read_text(encoding="utf-8-sig")) == dict(
        config
    )


def test_revocation_suppresses_pending_reply():
    from astrbot.core.pipeline.respond.stage import RespondStage

    config, event, _, stopped = setup_gate()
    cleared = []
    event.get_result = lambda: object()
    event.clear_result = lambda: cleared.append(True)
    stage = RespondStage()
    stage.config = config
    asyncio.run(stage.process(event))
    assert stopped and cleared


def test_segmented_reply_rechecks_after_wait(monkeypatch):
    from astrbot.core.message.components import Plain
    from astrbot.core.message.message_event_result import MessageEventResult
    from astrbot.core.pipeline.respond import stage as respond

    config, event, _, stopped = setup_gate(["onebot:FriendMessage:42"])
    sent = []
    result = MessageEventResult().message("secret")
    event.get_result = lambda: result
    event.get_extra = lambda *_args: False
    event.set_extra = lambda *_args: None
    event.get_sender_name = lambda: "test"
    event.get_sender_id = lambda: "42"
    event._outline_chain = lambda _chain: "test"
    event.clear_result = lambda: None

    async def send(chain):
        sent.append(chain)

    async def revoke(_seconds):
        config["platform_settings"]["dm_tiers"] = {}

    async def interval(_comp):
        return 0

    event.send = send
    stage = respond.RespondStage()
    stage.config = config
    stage.platform_settings = config["platform_settings"]
    stage.is_seg_reply_required = lambda _event: True
    stage._calc_comp_interval = interval
    monkeypatch.setattr(respond.asyncio, "sleep", revoke)
    assert isinstance(result.chain[0], Plain)
    asyncio.run(stage.process(event))
    assert stopped and not sent


def test_stream_rechecks_permission_between_chunks():
    from astrbot.core.message.message_event_result import (
        MessageEventResult,
        ResultContentType,
    )
    from astrbot.core.pipeline.respond.stage import RespondStage

    config, event, _, stopped = setup_gate(["onebot:FriendMessage:42"])
    consumed = []

    async def source():
        yield "first"
        config["platform_settings"]["dm_tiers"] = {}
        yield "private second"

    async def send_streaming(stream, _segmenting):
        async for chunk in stream:
            consumed.append(chunk)

    result = MessageEventResult()
    result.result_content_type = ResultContentType.STREAMING_RESULT
    result.async_stream = source()
    event.get_result = lambda: result
    event.get_extra = lambda *_args: False
    event.set_extra = lambda *_args: None
    event.get_sender_name = lambda: "test"
    event.get_sender_id = lambda: "42"
    event._outline_chain = lambda _chain: "test"
    event.clear_result = lambda: None
    event.get_platform_id = lambda: "onebot"
    event.send_streaming = send_streaming
    stage = RespondStage()
    stage.config = config
    with pytest.raises(PermissionError, match="dm_access_revoked"):
        asyncio.run(stage.process(event))
    assert consumed == ["first"] and stopped
