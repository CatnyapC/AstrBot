from ..register import register_provider_adapter
from .openai_source import ProviderOpenAIOfficial


@register_provider_adapter(
    "dashscope_coding_openai_chat_completion",
    "DashScope Coding OpenAI Provider Adapter",
)
class ProviderDashScopeCodingOpenAI(ProviderOpenAIOfficial):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)
