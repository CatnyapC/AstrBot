from __future__ import annotations

from astrbot.core.provider.provider import Provider

DEFAULT_LOCAL_MODEL_ID_PREFIXES = ["llama_cpp"]
DEFAULT_LOCAL_MODEL_MAX_AGENT_STEP = 2
DEFAULT_LOCAL_MODEL_TOOL_RESULT_MAX_CHARS = 1000


def normalize_local_model_prefixes(value: object) -> list[str]:
    if value is None:
        value = DEFAULT_LOCAL_MODEL_ID_PREFIXES
    if isinstance(value, str):
        raw_items = value.replace("\r", "\n").replace(",", "\n").splitlines()
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = DEFAULT_LOCAL_MODEL_ID_PREFIXES

    prefixes: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        prefix = str(item or "").strip()
        if not prefix or prefix in seen:
            continue
        prefixes.append(prefix)
        seen.add(prefix)
    return prefixes


def parse_non_negative_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def provider_identity_candidates(provider: Provider) -> list[str]:
    config = getattr(provider, "provider_config", {}) or {}
    provider_id = str(config.get("id") or "").strip()
    provider_type = str(config.get("type") or "").strip()
    model = str(provider.get_model() or "").strip()

    candidates = []
    for value in (
        provider_id,
        model,
        provider_type,
        f"{provider_id}/{model}" if provider_id and model else "",
        f"{provider_type}/{model}" if provider_type and model else "",
    ):
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def is_local_model_provider(provider: Provider, provider_settings: dict) -> bool:
    prefixes = normalize_local_model_prefixes(
        provider_settings.get("local_model_id_prefixes")
    )
    if not prefixes:
        return False
    return any(
        candidate.startswith(prefix)
        for candidate in provider_identity_candidates(provider)
        for prefix in prefixes
    )


def resolve_local_model_max_agent_step(
    provider: Provider,
    provider_settings: dict,
    configured_max_step: int,
) -> int:
    if not is_local_model_provider(provider, provider_settings):
        return configured_max_step

    local_limit = parse_non_negative_int(
        provider_settings.get("local_model_max_agent_step"),
        DEFAULT_LOCAL_MODEL_MAX_AGENT_STEP,
    )
    if local_limit <= 0:
        return configured_max_step
    return min(configured_max_step, local_limit)


def resolve_local_model_tool_result_max_chars(
    provider: Provider,
    provider_settings: dict,
) -> int:
    if not is_local_model_provider(provider, provider_settings):
        return 0
    return parse_non_negative_int(
        provider_settings.get("local_model_tool_result_max_chars"),
        DEFAULT_LOCAL_MODEL_TOOL_RESULT_MAX_CHARS,
    )
