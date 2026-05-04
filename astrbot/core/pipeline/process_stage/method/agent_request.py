from collections.abc import AsyncGenerator

from astrbot.core import logger
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.star.session_llm_manager import SessionServiceManager

from ...context import PipelineContext
from ..stage import Stage
from .agent_sub_stages.internal import InternalAgentSubStage
from .agent_sub_stages.third_party import ThirdPartyAgentSubStage


class AgentRequestSubStage(Stage):
    async def initialize(self, ctx: PipelineContext) -> None:
        self.ctx = ctx
        self.config = ctx.astrbot_config

        self.bot_wake_prefixs: list[str] = self.config["wake_prefix"]
        self.prov_wake_prefix: str = self.config["provider_settings"]["wake_prefix"]
        for bwp in self.bot_wake_prefixs:
            if self.prov_wake_prefix.startswith(bwp):
                logger.info(
                    f"识别 LLM 聊天额外唤醒前缀 {self.prov_wake_prefix} 以机器人唤醒前缀 {bwp} 开头，已自动去除。",
                )
                self.prov_wake_prefix = self.prov_wake_prefix[len(bwp) :]

        agent_runner_type = self.config["provider_settings"]["agent_runner_type"]
        if agent_runner_type == "local":
            self.agent_sub_stage = InternalAgentSubStage()
        else:
            self.agent_sub_stage = ThirdPartyAgentSubStage()
        await self.agent_sub_stage.initialize(ctx)

    async def process(self, event: AstrMessageEvent) -> AsyncGenerator[None, None]:
        router_timeout = bool(event.get_extra("_router_timeout_dispatched", False))
        has_provider_request = event.get_extra("provider_request") is not None
        if router_timeout or has_provider_request:
            logger.info(
                "AgentRequestSubStage enter: session=%s router_timeout=%s provider_request=%s call_llm=%s stopped=%s",
                event.unified_msg_origin,
                router_timeout,
                has_provider_request,
                event.call_llm,
                event.is_stopped(),
            )

        if not self.ctx.astrbot_config["provider_settings"]["enable"]:
            if router_timeout or has_provider_request:
                logger.info(
                    "AgentRequestSubStage skip: provider disabled session=%s",
                    event.unified_msg_origin,
                )
            logger.debug(
                "This pipeline does not enable AI capability, skip processing."
            )
            return

        if not await SessionServiceManager.should_process_llm_request(event):
            if router_timeout or has_provider_request:
                logger.info(
                    "AgentRequestSubStage skip: session llm disabled session=%s",
                    event.unified_msg_origin,
                )
            logger.debug(
                f"The session {event.unified_msg_origin} has disabled AI capability, skipping processing."
            )
            return

        async for resp in self.agent_sub_stage.process(event, self.prov_wake_prefix):
            yield resp
