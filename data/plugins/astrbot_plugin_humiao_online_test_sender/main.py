from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot.core.platform.sources.telegram.tg_adapter import TelegramPlatformAdapter
from astrbot.core.utils.path_utils import get_astrbot_plugin_data_path

PLUGIN_NAME = "astrbot_plugin_humiao_online_test_sender"
DEFAULT_GROUP_ID = "499574167"
PLATFORM_AIOCQHTTP = "aiocqhttp"
PLATFORM_TELEGRAM = "telegram"
PLATFORM_AUTO = "auto"
SUPPORTED_PLATFORM_TYPES = {PLATFORM_AIOCQHTTP, PLATFORM_TELEGRAM, PLATFORM_AUTO}


def _as_str(value: object) -> str:
    return str(value or "").strip()


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = _as_str(item)
            if text:
                out.append(text)
        return out
    if isinstance(value, str):
        parts = [_as_str(part) for part in value.split(",")]
        return [part for part in parts if part]
    return []


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: object, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except Exception:
        return max(minimum, int(default))


def _as_float(value: object, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(value))
    except Exception:
        return max(minimum, float(default))


def _as_optional_int(value: object, field_name: str) -> tuple[int | None, str | None]:
    text = _as_str(value)
    if not text:
        return None, None
    try:
        parsed = int(text)
    except Exception:
        return None, f"{field_name} must be numeric: {text}"
    if parsed <= 0:
        return None, f"{field_name} must be positive: {text}"
    return parsed, None


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _safe_str_attr(obj: object | None, attr_name: str) -> str:
    if obj is None:
        return ""
    try:
        return _as_str(getattr(obj, attr_name, ""))
    except Exception as exc:
        logger.debug(
            "[humiao_test_sender] optional attribute %s unavailable: %s",
            attr_name,
            exc,
        )
        return ""


def _platform_id(adapter: object) -> str:
    metadata = getattr(adapter, "metadata", None)
    if metadata is None and callable(getattr(adapter, "meta", None)):
        try:
            metadata = adapter.meta()
        except Exception:
            metadata = None
    inst_id = _as_str(getattr(metadata, "id", ""))
    if not inst_id:
        config = getattr(adapter, "config", {})
        if isinstance(config, dict):
            inst_id = _as_str(config.get("id", ""))
    return inst_id


def _adapter_platform_type(adapter: object) -> str:
    metadata = getattr(adapter, "metadata", None)
    if metadata is None and callable(getattr(adapter, "meta", None)):
        try:
            metadata = adapter.meta()
        except Exception:
            metadata = None
    name = _as_str(getattr(metadata, "name", "")).lower()
    if not name:
        config = getattr(adapter, "config", {})
        if isinstance(config, dict):
            name = _as_str(config.get("type") or config.get("platform")).lower()
    if isinstance(adapter, AiocqhttpAdapter):
        return PLATFORM_AIOCQHTTP
    if isinstance(adapter, TelegramPlatformAdapter):
        return PLATFORM_TELEGRAM
    return name


def _telegram_group_parts(group_id: str) -> tuple[int | None, int | None, str | None]:
    chat_id_text, sep, thread_id_text = group_id.partition("#")
    chat_id_text = _as_str(chat_id_text)
    if not chat_id_text:
        return None, None, "group_id is empty"
    try:
        chat_id = int(chat_id_text)
    except ValueError:
        return None, None, f"telegram chat_id must be numeric: {chat_id_text}"
    if not sep:
        return chat_id, None, None
    thread_id_text = _as_str(thread_id_text)
    if not thread_id_text:
        return None, None, f"telegram message_thread_id is empty: {group_id}"
    try:
        thread_id = int(thread_id_text)
    except ValueError:
        return (
            None,
            None,
            f"telegram message_thread_id must be numeric: {thread_id_text}",
        )
    return chat_id, thread_id, None


def _is_group_allowed(
    group_id: str,
    allowed_group_ids: tuple[str, ...],
    platform_type: str,
) -> bool:
    if group_id in allowed_group_ids:
        return True
    if platform_type == PLATFORM_TELEGRAM:
        chat_id_text = _as_str(group_id.partition("#")[0])
        return chat_id_text in allowed_group_ids
    return False


@dataclass(slots=True)
class PluginConfig:
    enabled: bool = True
    platform_type: str = PLATFORM_AIOCQHTTP
    humiao_platform_id: str = ""
    allowed_group_ids: tuple[str, ...] = (DEFAULT_GROUP_ID,)
    inbox_dir: str = ""
    report_dir: str = ""
    processing_dir: str = ""
    processed_dir: str = ""
    poll_interval_sec: float = 1.0
    send_interval_ms: int = 1500
    max_cases_per_run: int = 20
    max_message_chars: int = 400

    @classmethod
    def from_config(cls, config: AstrBotConfig | None) -> PluginConfig:
        if not config:
            return cls()

        def _cfg(*keys: str, default=None):
            for key in keys:
                if "." not in key:
                    if key in config:
                        return config.get(key, default)
                    continue
                head, tail = key.split(".", 1)
                container = config.get(head, {})
                if isinstance(container, dict) and tail in container:
                    return container.get(tail, default)
            return default

        allowed = _as_str_list(
            _cfg(
                "allowed_group_ids",
                "Basic.allowed_group_ids",
                default=[DEFAULT_GROUP_ID],
            )
        )
        if not allowed:
            allowed = [DEFAULT_GROUP_ID]
        platform_type = _as_str(
            _cfg("platform_type", "Basic.platform_type", default=PLATFORM_AIOCQHTTP)
        ).lower()
        if platform_type not in SUPPORTED_PLATFORM_TYPES:
            platform_type = PLATFORM_AIOCQHTTP
        return cls(
            enabled=_as_bool(_cfg("enabled", "Basic.enabled", default=True), True),
            platform_type=platform_type,
            humiao_platform_id=_as_str(
                _cfg("humiao_platform_id", "Basic.humiao_platform_id", default="")
            ),
            allowed_group_ids=tuple(allowed),
            inbox_dir=_as_str(_cfg("inbox_dir", "Paths.inbox_dir", default="")),
            report_dir=_as_str(_cfg("report_dir", "Paths.report_dir", default="")),
            processing_dir=_as_str(
                _cfg("processing_dir", "Paths.processing_dir", default="")
            ),
            processed_dir=_as_str(
                _cfg("processed_dir", "Paths.processed_dir", default="")
            ),
            poll_interval_sec=_as_float(
                _cfg("poll_interval_sec", "Runtime.poll_interval_sec", default=1.0),
                1.0,
                minimum=0.2,
            ),
            send_interval_ms=_as_int(
                _cfg("send_interval_ms", "Runtime.send_interval_ms", default=1500),
                1500,
                minimum=0,
            ),
            max_cases_per_run=_as_int(
                _cfg("max_cases_per_run", "Runtime.max_cases_per_run", default=20),
                20,
                minimum=1,
            ),
            max_message_chars=_as_int(
                _cfg("max_message_chars", "Runtime.max_message_chars", default=400),
                400,
                minimum=16,
            ),
        )


@register(
    PLUGIN_NAME,
    "lincoln",
    "Inbox-based humiao sender for live online test cases",
    "0.1.0",
)
class HumiaoOnlineTestSender(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.context = context
        self.config = PluginConfig.from_config(config)
        self._poll_task: asyncio.Task | None = None
        self._run_lock = asyncio.Lock()
        self._warned_missing_platform = False

        data_root = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self._data_root = data_root
        self._inbox_dir = (
            Path(self.config.inbox_dir).expanduser()
            if self.config.inbox_dir
            else data_root / "inbox"
        )
        self._report_dir = (
            Path(self.config.report_dir).expanduser()
            if self.config.report_dir
            else data_root / "reports"
        )
        self._processing_dir = (
            Path(self.config.processing_dir).expanduser()
            if self.config.processing_dir
            else data_root / "processing"
        )
        self._processed_dir = (
            Path(self.config.processed_dir).expanduser()
            if self.config.processed_dir
            else data_root / "processed"
        )

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        for path in (
            self._data_root,
            self._inbox_dir,
            self._report_dir,
            self._processing_dir,
            self._processed_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "[humiao_test_sender] started: inbox=%s report=%s",
            self._inbox_dir,
            self._report_dir,
        )

    async def terminate(self) -> None:
        task = self._poll_task
        self._poll_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self) -> None:
        while True:
            try:
                if self.config.enabled:
                    await self._process_next_manifest_if_any()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[humiao_test_sender] poll loop error: %s", exc)
            await asyncio.sleep(self.config.poll_interval_sec)

    async def _process_next_manifest_if_any(self) -> None:
        manifest_path = self._claim_next_manifest()
        if manifest_path is None:
            return
        async with self._run_lock:
            await self._process_manifest(manifest_path)

    def _claim_next_manifest(self) -> Path | None:
        for path in sorted(self._inbox_dir.glob("*.json")):
            target = self._processing_dir / path.name
            try:
                path.replace(target)
                return target
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.warning(
                    "[humiao_test_sender] claim manifest failed: %s (%s)",
                    path,
                    exc,
                )
        return None

    def _resolve_adapter(self) -> AiocqhttpAdapter | TelegramPlatformAdapter | None:
        platform_id = self.config.humiao_platform_id
        if not platform_id:
            if not self._warned_missing_platform:
                logger.warning(
                    "[humiao_test_sender] humiao_platform_id is empty; sender stays idle."
                )
                self._warned_missing_platform = True
            return None
        matches: list[AiocqhttpAdapter | TelegramPlatformAdapter] = []
        for inst in self.context.platform_manager.get_insts():
            inst_type = _adapter_platform_type(inst)
            if (
                self.config.platform_type != PLATFORM_AUTO
                and inst_type != self.config.platform_type
            ):
                continue
            if inst_type not in {PLATFORM_AIOCQHTTP, PLATFORM_TELEGRAM}:
                continue
            if _platform_id(inst) == platform_id:
                matches.append(inst)
        if len(matches) != 1:
            logger.warning(
                "[humiao_test_sender] platform_type=%s platform_id=%s matched %s adapters",
                self.config.platform_type,
                platform_id,
                len(matches),
            )
            return None
        self._warned_missing_platform = False
        return matches[0]

    async def _process_manifest(self, manifest_path: Path) -> None:
        run_id = manifest_path.stem
        started_at = time.time()
        report: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "failed",
            "started_at": started_at,
            "completed_at": started_at,
            "platform_type": self.config.platform_type,
            "platform_id": self.config.humiao_platform_id,
            "allowed_group_ids": list(self.config.allowed_group_ids),
            "cases": [],
        }
        try:
            manifest = self._load_manifest(manifest_path)
            cases = manifest.get("cases") if isinstance(manifest, dict) else None
            if not isinstance(cases, list):
                raise ValueError("manifest cases must be a list")
            adapter = self._resolve_adapter()
            if adapter is None:
                raise RuntimeError("humiao adapter unavailable")
            adapter_self_id = _as_str(getattr(adapter, "client_self_id", ""))
            adapter_id = _platform_id(adapter)
            adapter_platform_type = _adapter_platform_type(adapter)
            report["adapter_self_id"] = adapter_self_id
            report["adapter_id"] = adapter_id
            report["resolved_platform_type"] = adapter_platform_type
            report.update(self._sender_identity(adapter))
            default_group_id = _as_str(manifest.get("default_group_id"))
            default_delay_ms = _as_int(
                manifest.get("send_interval_ms"),
                self.config.send_interval_ms,
                minimum=0,
            )
            partial_failure = False
            capped_cases = cases[: self.config.max_cases_per_run]
            for idx, item in enumerate(capped_cases):
                case_report = await self._send_case(
                    adapter,
                    item if isinstance(item, dict) else {},
                    default_group_id=default_group_id,
                    default_delay_ms=default_delay_ms,
                    adapter_self_id=adapter_self_id,
                    adapter_id=adapter_id,
                    platform_type=adapter_platform_type,
                )
                report["cases"].append(case_report)
                if _as_str(case_report.get("status")) != "sent":
                    partial_failure = True
                if idx + 1 < len(capped_cases):
                    delay_ms = _as_int(
                        case_report.get("send_delay_ms"),
                        default_delay_ms,
                        minimum=0,
                    )
                    if delay_ms > 0:
                        await asyncio.sleep(delay_ms / 1000.0)
            report["status"] = "partial" if partial_failure else "completed"
        except Exception as exc:
            report["error"] = str(exc)
            logger.exception("[humiao_test_sender] process manifest failed: %s", exc)
        finally:
            report["completed_at"] = time.time()
            self._write_report(run_id, report)
            self._finalize_manifest(manifest_path)

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("manifest root must be object")
        return data

    def _write_report(self, run_id: str, report: dict[str, Any]) -> None:
        target = self._report_dir / f"{run_id}.json"
        temp = self._report_dir / f".{run_id}.tmp"
        temp.write_text(
            json.dumps(_json_safe(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(target)

    def _finalize_manifest(self, manifest_path: Path) -> None:
        target = self._processed_dir / manifest_path.name
        try:
            manifest_path.replace(target)
        except Exception:
            try:
                manifest_path.unlink(missing_ok=True)
            except Exception:
                return

    def _sender_identity(self, adapter: object) -> dict[str, str]:
        identity: dict[str, str] = {}
        config = getattr(adapter, "config", {})
        if isinstance(config, dict):
            for keys, field_name in (
                (("bot_id", "telegram_bot_id", "sender_bot_id"), "sender_bot_id"),
                (
                    ("username", "bot_username", "telegram_bot_username"),
                    "sender_bot_username",
                ),
                (
                    ("first_name", "bot_first_name", "telegram_bot_first_name"),
                    "sender_bot_first_name",
                ),
            ):
                value = _as_str(
                    next((config.get(key) for key in keys if config.get(key)), "")
                )
                if value:
                    identity[field_name] = value
        client = (
            self._telegram_client(adapter)
            if _adapter_platform_type(adapter) == PLATFORM_TELEGRAM
            else None
        )
        for attr_name, field_name in (
            ("id", "sender_bot_id"),
            ("username", "sender_bot_username"),
            ("first_name", "sender_bot_first_name"),
        ):
            value = _safe_str_attr(client, attr_name)
            if value and field_name not in identity:
                identity[field_name] = value
        return identity

    def _telegram_client(self, adapter: object) -> object | None:
        try:
            get_client = getattr(adapter, "get_client", None)
            if callable(get_client):
                return get_client()
            return getattr(adapter, "client", None)
        except Exception as exc:
            logger.debug("[humiao_test_sender] telegram client unavailable: %s", exc)
            return None

    async def _send_case(
        self,
        adapter: AiocqhttpAdapter | TelegramPlatformAdapter,
        case: dict[str, Any],
        *,
        default_group_id: str,
        default_delay_ms: int,
        adapter_self_id: str,
        adapter_id: str,
        platform_type: str,
    ) -> dict[str, Any]:
        case_id = _as_str(case.get("case_id")) or f"case-{int(time.time() * 1000)}"
        group_id = _as_str(case.get("group_id")) or default_group_id
        message = case.get("message") if isinstance(case.get("message"), dict) else {}
        text = _as_str(message.get("text"))
        at_user_ids = _as_str_list(message.get("at_user_ids"))
        reply_to_message_id, reply_error = _as_optional_int(
            message.get("reply_to_message_id"),
            "message.reply_to_message_id",
        )
        send_delay_ms = _as_int(case.get("send_delay_ms"), default_delay_ms, minimum=0)
        report: dict[str, Any] = {
            "case_id": case_id,
            "platform_type": platform_type,
            "adapter_id": adapter_id,
            "group_id": group_id,
            "sender_user_id": adapter_self_id,
            "message": {"text": text, "at_user_ids": at_user_ids},
            "send_delay_ms": send_delay_ms,
            "status": "failed",
            "sent_at": 0.0,
            "raw_message_id": "",
        }
        if reply_to_message_id is not None:
            report["message"]["reply_to_message_id"] = reply_to_message_id
        if not _is_group_allowed(
            group_id, self.config.allowed_group_ids, platform_type
        ):
            report["error"] = f"group not allowed: {group_id}"
            return report
        if reply_error:
            report["error"] = reply_error
            return report
        if platform_type == PLATFORM_AIOCQHTTP and not group_id.isdigit():
            report["error"] = f"group_id must be numeric: {group_id}"
            return report
        if not text:
            report["error"] = "message.text is empty"
            return report
        if len(text) > self.config.max_message_chars:
            report["error"] = (
                f"message.text too long: {len(text)} > {self.config.max_message_chars}"
            )
            return report

        if platform_type == PLATFORM_TELEGRAM:
            return await self._send_telegram_case(
                adapter,
                report,
                case_id=case_id,
                group_id=group_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
        return await self._send_aiocqhttp_case(
            adapter,
            report,
            case_id=case_id,
            group_id=group_id,
            text=text,
            at_user_ids=at_user_ids,
        )

    async def _send_aiocqhttp_case(
        self,
        adapter: AiocqhttpAdapter,
        report: dict[str, Any],
        *,
        case_id: str,
        group_id: str,
        text: str,
        at_user_ids: list[str],
    ) -> dict[str, Any]:
        payload: list[dict[str, Any]] = []
        for user_id in at_user_ids:
            payload.append({"type": "at", "data": {"qq": user_id}})
        if payload and text and not text.startswith(" "):
            payload.append({"type": "text", "data": {"text": " "}})
        payload.append({"type": "text", "data": {"text": text}})

        sent_at = time.time()
        result = await adapter.bot.call_action(
            "send_group_msg",
            group_id=int(group_id),
            message=payload,
        )
        raw_message_id = ""
        if isinstance(result, dict):
            raw_message_id = _as_str(
                result.get("message_id") or result.get("messageId")
            )
        elif result is not None:
            raw_message_id = _as_str(result)
        report.update(
            {
                "status": "sent",
                "sent_at": sent_at,
                "raw_message_id": raw_message_id,
                "send_response": _json_safe(result),
            }
        )
        logger.info(
            "[humiao_test_sender] sent aiocqhttp case=%s group=%s raw_message_id=%s text=%r",
            case_id,
            group_id,
            raw_message_id,
            text,
        )
        return report

    async def _send_telegram_case(
        self,
        adapter: TelegramPlatformAdapter,
        report: dict[str, Any],
        *,
        case_id: str,
        group_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        chat_id, thread_id, error = _telegram_group_parts(group_id)
        if error:
            report["error"] = error
            return report
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        client = self._telegram_client(adapter)
        if client is None or not callable(getattr(client, "send_message", None)):
            report["error"] = "telegram client.send_message unavailable"
            return report

        sent_at = time.time()
        result = await client.send_message(**payload)
        message_id = ""
        if isinstance(result, dict):
            message_id = _as_str(result.get("message_id") or result.get("messageId"))
        else:
            message_id = _as_str(getattr(result, "message_id", "")) or _as_str(result)
        report.update(
            {
                "status": "sent",
                "sent_at": sent_at,
                "raw_message_id": message_id,
                "telegram_message_id": message_id,
                "telegram_chat_id": chat_id,
                "telegram_send_payload": payload,
                "send_response": _json_safe(result),
                "send_response_summary": _as_str(result),
            }
        )
        if thread_id is not None:
            report["telegram_message_thread_id"] = thread_id
        if reply_to_message_id is not None:
            report["telegram_reply_to_message_id"] = reply_to_message_id
        logger.info(
            "[humiao_test_sender] sent telegram case=%s group=%s message_id=%s text=%r",
            case_id,
            group_id,
            message_id,
            text,
        )
        return report
