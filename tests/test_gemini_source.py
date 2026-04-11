import asyncio
import logging
from types import SimpleNamespace

from google.genai import types

from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.sources.gemini_source import ProviderGoogleGenAI


def test_gemini_custom_extra_body_maps_max_tokens():
    provider = object.__new__(ProviderGoogleGenAI)
    provider.provider_config = {"custom_extra_body": {"max_tokens": 96, "top_p": 0.7}}

    result = provider._normalize_custom_config_kwargs({"temperature": 0.2})

    assert result["temperature"] == 0.2
    assert result["top_p"] == 0.7
    assert result["max_output_tokens"] == 96
    assert "max_tokens" not in result


def test_gemini_sanitize_leaked_reasoning_text_extracts_final_reply():
    leaked = """
*   User (漓漓) said: "晚上好"
*   Draft 1: 漓漓晚上好！狐米一直在等漓漓出现呢。【轻快地摇了摇尾巴，凑近漓漓嗅了嗅】
*   Selected response:* 漓漓晚上好！狐米刚好在想漓漓呢。【轻快地摇了摇尾巴，凑近漓漓嗅了嗅】
Final Polish:
    "漓漓晚上好！狐米一直在等漓漓出现呢。【轻快地摇了摇尾巴，凑近漓漓嗅了嗅】"
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "漓漓晚上好！狐米一直在等漓漓出现呢。【轻快地摇了摇尾巴，凑近漓漓嗅了嗅】"
    )


def test_gemini_sanitize_repeated_text_dedupes_exact_repeat():
    repeated = "晚上好呀。【摇摇尾巴】晚上好呀。【摇摇尾巴】"

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(repeated)
        == "晚上好呀。【摇摇尾巴】"
    )


def test_gemma_channel_answer_extracts_final_reply():
    leaked = """
<|channel>thought
*   Think step 1
*   Think step 2
<channel|>漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】"
    )


def test_gemma_channel_answer_extracts_final_reply_after_empty_thought_block():
    leaked = """
<|channel>thought
<channel|>唔，让狐再努力搜寻一下记忆...不过现在狐满脑子都是可乐呀！【狐米有些俏皮地眨了眨眼】
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "唔，让狐再努力搜寻一下记忆...不过现在狐满脑子都是可乐呀！【狐米有些俏皮地眨了眨眼】"
    )


def test_gemini_detects_partial_reasoning_markers():
    assert ProviderGoogleGenAI._looks_like_leaked_reasoning("Draft")
    assert ProviderGoogleGenAI._looks_like_leaked_reasoning("Selected response")
    assert not ProviderGoogleGenAI._looks_like_leaked_reasoning(
        "晚上好呀。【摇摇尾巴】"
    )


def test_gemini_sanitize_prefers_revised_tail_and_strips_instruction_prefix():
    leaked = """
Wait, the prompt says "不要使用中文引号、英文引号包裹整句台词".
The draft is fine.

Revised:
不要使用中文引号、英文引号包裹整句台词 艾可弟弟超级可爱的！狐记得艾可有青蓝色的角，整体是淡紫色的，眼睛圆圆的，尾巴也蓬松得像云朵一样！【狐米歪了歪头，水色耳饰在耳边轻轻晃动】
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "艾可弟弟超级可爱的！狐记得艾可有青蓝色的角，整体是淡紫色的，眼睛圆圆的，尾巴也蓬松得像云朵一样！【狐米歪了歪头，水色耳饰在耳边轻轻晃动】"
    )


def test_gemini_sanitize_ignores_quoted_instruction_tail():
    leaked = """
* Final Version:
    漓漓，狐记得可乐是一只超级可爱的小狼，有着圆圆的大蓝眼睛，腿也特别长哦！【狐米轻快地晃了晃蓬松的尾巴】

* Wait, the prompt says:* "在发言中多次需要指代自己时，经常使用狐称呼自己。"
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "漓漓，狐记得可乐是一只超级可爱的小狼，有着圆圆的大蓝眼睛，腿也特别长哦！【狐米轻快地晃了晃蓬松的尾巴】"
    )


def test_gemini_prepare_query_config_disables_include_thoughts():
    provider = object.__new__(ProviderGoogleGenAI)
    provider.provider_config = {"gm_thinking_config": {"budget": 0}}
    provider.provider_settings = {}
    provider.safety_settings = []
    provider.model_name = "gemini-2.5-flash"

    config = asyncio.run(
        provider._prepare_query_config(
            payloads={"model": "gemini-2.5-flash", "messages": []},
        )
    )

    assert config.thinking_config is not None
    assert config.thinking_config.include_thoughts is False
    assert config.thinking_config.thinking_budget == 0


def test_gemini_logs_prohibited_empty_candidates_as_warning(caplog):
    result = SimpleNamespace(
        candidates=None,
        prompt_feedback=SimpleNamespace(block_reason="PROHIBITED_CONTENT"),
    )

    with caplog.at_level(logging.WARNING, logger="astrbot"):
        ProviderGoogleGenAI._log_empty_candidates_response(result)

    assert caplog.records[-1].levelno == logging.WARNING
    assert "返回的 candidates 为空" in caplog.records[-1].message


def test_gemini_logs_other_empty_candidates_as_error(caplog):
    result = SimpleNamespace(candidates=None, prompt_feedback=None)

    with caplog.at_level(logging.ERROR, logger="astrbot"):
        ProviderGoogleGenAI._log_empty_candidates_response(result)

    assert caplog.records[-1].levelno == logging.ERROR
    assert "返回的 candidates 为空" in caplog.records[-1].message


def test_gemma_prepare_query_config_disables_include_thoughts():
    provider = object.__new__(ProviderGoogleGenAI)
    provider.provider_config = {}
    provider.provider_settings = {}
    provider.safety_settings = []
    provider.model_name = "gemma-4-26b-a4b-it"

    config = asyncio.run(
        provider._prepare_query_config(
            payloads={"model": "gemma-4-26b-a4b-it", "messages": []},
        )
    )

    assert config.thinking_config is not None
    assert config.thinking_config.include_thoughts is False


def test_gemini_query_stream_suppresses_sanitized_leak_chunks():
    async def collect():
        provider = object.__new__(ProviderGoogleGenAI)
        provider.provider_config = {}
        provider.provider_settings = {}
        provider.safety_settings = []
        provider.model_name = "gemma-4-31b-it"
        provider._prepare_conversation = lambda payloads: []

        async def fake_prepare_query_config(*args, **kwargs):
            return None

        provider._prepare_query_config = fake_prepare_query_config

        leaked_text = """
Draft 1: 唔，让狐再努力搜寻一下记忆...不过现在狐满脑子都是可乐呢！【狐米有些俏皮地眨了眨眼】
Final version:
唔，让狐再努力搜寻一下记忆...不过现在狐满脑子都是可乐呀！【狐米有些俏皮地眨了眨眼】
"""
        part = SimpleNamespace(
            text=leaked_text,
            function_call=None,
            inline_data=None,
            thought_signature=None,
            thought=False,
        )
        candidate = SimpleNamespace(
            content=SimpleNamespace(parts=[part]),
            finish_reason=types.FinishReason.STOP,
        )
        chunk = SimpleNamespace(
            candidates=[candidate],
            text=leaked_text,
            response_id="resp_1",
            usage_metadata=None,
        )

        class _FakeModels:
            async def generate_content_stream(self, **kwargs):
                async def _gen():
                    yield chunk

                return _gen()

        provider.client = SimpleNamespace(models=_FakeModels())

        results = []
        async for item in provider._query_stream(
            payloads={"messages": [], "model": "gemma-4-31b-it"},
            tools=None,
        ):
            results.append(item)
        return results

    results = asyncio.run(collect())

    assert len(results) == 1
    assert results[0].is_chunk is False
    assert (
        results[0].completion_text
        == "唔，让狐再努力搜寻一下记忆...不过现在狐满脑子都是可乐呀！【狐米有些俏皮地眨了眨眼】"
    )


def test_gemma_query_stream_buffers_plain_text_until_final():
    async def collect():
        provider = object.__new__(ProviderGoogleGenAI)
        provider.provider_config = {}
        provider.provider_settings = {}
        provider.safety_settings = []
        provider.model_name = "gemma-4-31b-it"
        provider._prepare_conversation = lambda payloads: []

        async def fake_prepare_query_config(*args, **kwargs):
            return None

        provider._prepare_query_config = fake_prepare_query_config

        plain_text = "漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】"
        part = SimpleNamespace(
            text=plain_text,
            function_call=None,
            inline_data=None,
            thought_signature=None,
            thought=False,
        )
        candidate = SimpleNamespace(
            content=SimpleNamespace(parts=[part]),
            finish_reason=types.FinishReason.STOP,
        )
        chunk = SimpleNamespace(
            candidates=[candidate],
            text=plain_text,
            response_id="resp_2",
            usage_metadata=None,
        )

        class _FakeModels:
            async def generate_content_stream(self, **kwargs):
                async def _gen():
                    yield chunk

                return _gen()

        provider.client = SimpleNamespace(models=_FakeModels())

        results = []
        async for item in provider._query_stream(
            payloads={"messages": [], "model": "gemma-4-31b-it"},
            tools=None,
        ):
            results.append(item)
        return results

    results = asyncio.run(collect())

    assert len(results) == 1
    assert results[0].is_chunk is False
    assert (
        results[0].completion_text
        == "漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】"
    )


def test_gemma_text_chat_stream_forces_non_stream_query():
    async def collect():
        provider = object.__new__(ProviderGoogleGenAI)
        provider.provider_config = {}
        provider.provider_settings = {}
        provider.safety_settings = []
        provider.api_keys = ["test-key"]
        provider.model_name = "gemma-4-31b-it"
        provider._ensure_message_to_dicts = lambda contexts: []

        async def fake_non_stream_query(payloads, func_tool):
            return LLMResponse(
                role="assistant",
                completion_text="漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】",
            )

        async def fake_stream_query(payloads, func_tool):
            raise AssertionError("_query_stream should not be used for gemma models")
            yield  # pragma: no cover

        provider._query = fake_non_stream_query
        provider._query_stream = fake_stream_query

        results = []
        async for item in provider.text_chat_stream(
            prompt=None,
            contexts=[],
            model="gemma-4-31b-it",
        ):
            results.append(item)
        return results

    results = asyncio.run(collect())

    assert len(results) == 1
    assert results[0].is_chunk is False
    assert (
        results[0].completion_text
        == "漓漓，狐记得可乐是一只超级可爱的小狼！【狐米晃了晃尾巴】"
    )


def test_gemini_sanitize_prefers_final_answer_construction_over_quotes():
    leaked = """
*   Wait, I should check if "狐米" is allowed to use "狐" as a pronoun.
    *   "在发言中多次需要指代自己时，经常使用狐称呼自己。"
    *   Yes.

    *   Final Answer Construction:
        漓漓，狐记得可乐是一只超级可爱的小狼，有着圆圆的大蓝眼睛，腿也特别长哦！【狐米轻快地晃了晃蓬松的尾巴】
"""

    assert (
        ProviderGoogleGenAI._sanitize_leaked_reasoning_text(leaked)
        == "漓漓，狐记得可乐是一只超级可爱的小狼，有着圆圆的大蓝眼睛，腿也特别长哦！【狐米轻快地晃了晃蓬松的尾巴】"
    )
