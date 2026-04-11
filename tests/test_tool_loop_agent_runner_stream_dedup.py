import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.response import AgentResponse
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse, ProviderRequest, TokenUsage
from astrbot.core.provider.provider import Provider


class StreamingDuplicateProvider(Provider):
    def __init__(self):
        super().__init__({}, {})

    def get_current_key(self) -> str:
        return "test_key"

    def set_key(self, key: str):
        pass

    async def get_models(self) -> list[str]:
        return ["test_model"]

    async def text_chat(self, **kwargs) -> LLMResponse:
        return LLMResponse(
            role="assistant",
            completion_text="不会被调用",
            usage=TokenUsage(input_other=1, output=1),
        )

    async def text_chat_stream(self, **kwargs):
        yield LLMResponse(
            role="assistant",
            result_chain=MessageChain().message("最终答案"),
            is_chunk=True,
        )
        yield LLMResponse(
            role="assistant",
            completion_text="最终答案",
            is_chunk=False,
            usage=TokenUsage(input_other=1, output=1),
        )


class MockHooks(BaseAgentRunHooks):
    async def on_agent_begin(self, run_context):
        return None

    async def on_agent_done(self, run_context, llm_response):
        return None


@pytest.mark.asyncio
async def test_streaming_text_not_reemitted_as_final_result():
    runner = ToolLoopAgentRunner()
    provider = StreamingDuplicateProvider()
    request = ProviderRequest(prompt="hi", func_tool=None, contexts=[])

    await runner.reset(
        provider=provider,
        request=request,
        run_context=ContextWrapper(context=None),
        tool_executor=None,
        agent_hooks=MockHooks(),
        streaming=True,
    )

    responses: list[AgentResponse] = []
    async for response in runner.step_until_done(max_steps=1):
        responses.append(response)

    streaming_responses = [r for r in responses if r.type == "streaming_delta"]
    final_responses = [r for r in responses if r.type == "llm_result"]

    assert len(streaming_responses) == 1
    assert streaming_responses[0].data["chain"].get_plain_text() == "最终答案"
    assert len(final_responses) == 0
    assert runner.final_llm_resp is not None
    assert runner.final_llm_resp.completion_text == "最终答案"
