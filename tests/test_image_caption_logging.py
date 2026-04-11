import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from astrbot.api.message_components import Image, Reply
from astrbot.api.platform import MessageType
from astrbot.builtin_stars.astrbot.long_term_memory import LongTermMemory
from astrbot.core.provider.entities import ProviderRequest


def _load_astr_main_agent_module():
    hooks_module_name = "astrbot.core.astr_agent_hooks"
    original_hooks = sys.modules.get(hooks_module_name)
    sys.modules.pop("astrbot.core.astr_main_agent", None)

    stub_hooks = ModuleType(hooks_module_name)
    stub_hooks.MAIN_AGENT_HOOKS = []
    sys.modules[hooks_module_name] = stub_hooks
    try:
        return importlib.import_module("astrbot.core.astr_main_agent")
    finally:
        if original_hooks is not None:
            sys.modules[hooks_module_name] = original_hooks
        else:
            sys.modules.pop(hooks_module_name, None)


@pytest.mark.asyncio
async def test_ensure_img_caption_warns_on_caption_failure():
    astr_main_agent = _load_astr_main_agent_module()
    req = ProviderRequest(image_urls=["file:///tmp/test-image.png"])

    with (
        patch.object(
            astr_main_agent,
            "_request_img_caption",
            AsyncMock(side_effect=RuntimeError("prohibited content")),
        ),
        patch.object(astr_main_agent.logger, "warning") as mock_warning,
        patch.object(astr_main_agent.logger, "error") as mock_error,
    ):
        await astr_main_agent._ensure_img_caption(
            req, {}, SimpleNamespace(), "caption-provider"
        )

    mock_warning.assert_called_once()
    mock_error.assert_not_called()
    assert req.image_urls == ["file:///tmp/test-image.png"]
    assert req.extra_user_content_parts == []


@pytest.mark.asyncio
async def test_process_quote_message_warns_on_quote_caption_failure():
    astr_main_agent = _load_astr_main_agent_module()
    req = ProviderRequest()
    reply = Reply(
        id="1",
        message_str="quoted text",
        sender_nickname="Alice",
        chain=[Image("file:///tmp/test-image.png")],
    )
    event = SimpleNamespace(message_obj=SimpleNamespace(message=[reply]))
    plugin_context = SimpleNamespace(
        get_provider_by_id=Mock(side_effect=RuntimeError("prohibited content"))
    )

    with (
        patch.object(astr_main_agent.logger, "warning") as mock_warning,
        patch.object(astr_main_agent.logger, "error") as mock_error,
    ):
        await astr_main_agent._process_quote_message(
            event, req, "caption-provider", plugin_context
        )

    mock_warning.assert_called_once()
    mock_error.assert_not_called()
    assert len(req.extra_user_content_parts) == 1
    assert "quoted text" in req.extra_user_content_parts[0].text


@pytest.mark.asyncio
async def test_long_term_memory_warns_on_caption_failure():
    context = SimpleNamespace()
    memory = LongTermMemory(SimpleNamespace(), context)
    event = SimpleNamespace(
        unified_msg_origin="group:1",
        message_obj=SimpleNamespace(sender=SimpleNamespace(nickname="Alice")),
        get_message_type=lambda: MessageType.GROUP_MESSAGE,
        get_messages=lambda: [Image("file:///tmp/test-image.png")],
    )

    with (
        patch.object(
            memory,
            "cfg",
            return_value={
                "max_cnt": 10,
                "image_caption": True,
                "image_caption_prompt": "prompt",
                "image_caption_provider_id": "caption-provider",
                "enable_active_reply": False,
                "ar_method": "possibility_reply",
                "ar_possibility": 0.0,
                "ar_prompt": "",
                "ar_whitelist": [],
            },
        ),
        patch.object(
            memory,
            "get_image_caption",
            AsyncMock(side_effect=RuntimeError("prohibited content")),
        ),
        patch(
            "astrbot.builtin_stars.astrbot.long_term_memory.logger.warning"
        ) as mock_warning,
        patch(
            "astrbot.builtin_stars.astrbot.long_term_memory.logger.error"
        ) as mock_error,
    ):
        await memory.handle_message(event)

    mock_warning.assert_called_once()
    mock_error.assert_not_called()
