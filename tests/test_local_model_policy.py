from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.agent.message import ToolCallMessageSegment
from astrbot.core.utils.local_model_policy import (
    is_local_model_provider,
    normalize_local_model_prefixes,
    resolve_local_model_max_agent_step,
    resolve_local_model_tool_result_max_chars,
)


class FakeProvider:
    def __init__(self, provider_id: str, model: str, provider_type: str = "openai"):
        self.provider_config = {"id": provider_id, "type": provider_type}
        self._model = model

    def get_model(self) -> str:
        return self._model


def test_normalize_local_model_prefixes_accepts_string_or_list():
    assert normalize_local_model_prefixes("llama_cpp, local/") == [
        "llama_cpp",
        "local/",
    ]
    assert normalize_local_model_prefixes(["llama_cpp", "", "llama_cpp"]) == [
        "llama_cpp"
    ]


def test_local_model_policy_matches_provider_id_model_pair():
    provider = FakeProvider(
        "llama_cpp",
        "google_gemma-4-26B-A4B-it-IQ4_XS.gguf",
    )
    settings = {
        "local_model_id_prefixes": ["llama_cpp/google_gemma"],
        "local_model_max_agent_step": 2,
        "local_model_tool_result_max_chars": 1000,
    }

    assert is_local_model_provider(provider, settings)
    assert resolve_local_model_max_agent_step(provider, settings, 30) == 2
    assert resolve_local_model_tool_result_max_chars(provider, settings) == 1000


def test_local_model_policy_does_not_raise_global_step_limit():
    provider = FakeProvider("llama_cpp", "small.gguf")
    settings = {
        "local_model_id_prefixes": ["llama_cpp"],
        "local_model_max_agent_step": 2,
    }

    assert resolve_local_model_max_agent_step(provider, settings, 1) == 1


def test_tool_loop_runner_char_limit_keeps_prefix():
    runner = ToolLoopAgentRunner()
    runner.tool_result_max_chars = 64

    result = runner._limit_inline_tool_result_chars("a" * 200)

    assert len(result) <= 64
    assert result.startswith("a")
    assert "truncated" in result


def test_tool_loop_runner_round_budget_uses_existing_blocks():
    runner = ToolLoopAgentRunner()
    runner.tool_result_max_chars = 64
    blocks = [
        ToolCallMessageSegment(
            role="tool",
            tool_call_id="call_1",
            content="a" * 60,
        )
    ]

    assert runner._remaining_tool_result_chars(blocks) == 4
