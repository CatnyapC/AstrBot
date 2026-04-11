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

    assert ProviderGoogleGenAI._sanitize_leaked_reasoning_text(repeated) == "晚上好呀。【摇摇尾巴】"


def test_gemini_detects_partial_reasoning_markers():
    assert ProviderGoogleGenAI._looks_like_leaked_reasoning("Draft")
    assert ProviderGoogleGenAI._looks_like_leaked_reasoning("Selected response")
    assert not ProviderGoogleGenAI._looks_like_leaked_reasoning("晚上好呀。【摇摇尾巴】")


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
