from ..register import register_provider_adapter
from .anthropic_source import ProviderAnthropic


@register_provider_adapter(
    "dashscope_coding_anthropic_chat_completion",
    "DashScope Coding Anthropic Provider Adapter",
)
class ProviderDashScopeCodingAnthropic(ProviderAnthropic):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)
