from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.pipeline.process_stage.method.agent_sub_stages.internal import (
    InternalAgentSubStage,
    _agent_session_lock_key,
)


class _Event:
    unified_msg_origin = "platform:group:1"

    def __init__(self, extras=None):
        self._extras = dict(extras or {})

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)


def test_agent_session_lock_key_uses_opt_in_override() -> None:
    assert _agent_session_lock_key(_Event()) == "platform:group:1"
    assert (
        _agent_session_lock_key(
            _Event({"_astrbot_session_lock_key": "platform:group:1#lane:2"})
        )
        == "platform:group:1#lane:2"
    )


@pytest.mark.asyncio
async def test_save_to_history_can_skip_conversation_write() -> None:
    stage = InternalAgentSubStage.__new__(InternalAgentSubStage)
    stage.conv_manager = SimpleNamespace(update_conversation=AsyncMock())
    event = _Event({"_astrbot_skip_conversation_save": True})
    req = SimpleNamespace(conversation=SimpleNamespace(cid="cid"), tool_calls_result=None)
    resp = SimpleNamespace(role="assistant", completion_text="ok", usage=None)

    await stage._save_to_history(event, req, resp, [], None)

    stage.conv_manager.update_conversation.assert_not_called()
