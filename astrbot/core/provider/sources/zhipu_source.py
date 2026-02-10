# This file was originally created to adapt to glm-4v-flash, which only supports one image in the context.
# It is no longer specifically adapted to Zhipu's models. To ensure compatibility, this


from __future__ import annotations

import json

from ..register import register_provider_adapter
from .openai_source import ProviderOpenAIOfficial


@register_provider_adapter("zhipu_chat_completion", "智谱 Chat Completion 提供商适配器")
class ProviderZhipu(ProviderOpenAIOfficial):
    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)

    async def _prepare_chat_payload(
        self,
        prompt: str | None,
        image_urls: list[str] | None = None,
        contexts: list[dict] | list | None = None,
        system_prompt: str | None = None,
        tool_calls_result=None,
        model: str | None = None,
        extra_user_content_parts=None,
        **kwargs,
    ) -> tuple:
        payloads, context_query = await super()._prepare_chat_payload(
            prompt=prompt,
            image_urls=image_urls,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            model=model,
            extra_user_content_parts=extra_user_content_parts,
            **kwargs,
        )
        self._normalize_zhipu_messages(payloads)
        return payloads, context_query

    @staticmethod
    def _flatten_content(content) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and "text" in part:
                        parts.append(str(part["text"]))
                    elif "text" in part:
                        parts.append(str(part["text"]))
                    elif part.get("type") in {"image", "image_url"}:
                        parts.append("[image]")
                    else:
                        parts.append(json.dumps(part, ensure_ascii=False))
                else:
                    parts.append(str(part))
            return " ".join(p for p in parts if p).strip()
        return str(content)

    def _normalize_zhipu_messages(self, payloads: dict) -> None:
        messages = payloads.get("messages", [])
        if not isinstance(messages, list):
            return
        normalized = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = self._flatten_content(msg.get("content"))

            if role == "tool":
                normalized.append(
                    {
                        "role": "user",
                        "content": f"[Tool Result] {content}".strip(),
                    }
                )
                continue

            if role == "assistant" and msg.get("tool_calls"):
                tool_calls = msg.get("tool_calls") or []
                tool_names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        name = (
                            tc.get("function", {}).get("name")
                            or tc.get("name")
                            or "tool"
                        )
                        tool_names.append(name)
                extra = f"[Tool Calls] {', '.join(tool_names)}" if tool_names else ""
                text = content
                if extra:
                    text = (text + "\n" if text else "") + extra
                normalized.append(
                    {
                        "role": "assistant",
                        "content": text or "[Tool call performed]",
                    }
                )
                continue

            new_msg = dict(msg)
            new_msg["content"] = content
            new_msg.pop("tool_calls", None)
            new_msg.pop("tool_call_id", None)
            normalized.append(new_msg)

        payloads["messages"] = normalized
