import asyncio
import json
import re
import uuid
from pathlib import Path

import aiohttp

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from ..entities import ProviderType
from ..provider import TTSProvider
from ..register import register_provider_adapter


@register_provider_adapter(
    provider_type_name="gsv_tts_selfhost",
    desc="GPT-SoVITS TTS(本地加载)",
    provider_type=ProviderType.TEXT_TO_SPEECH,
)
class ProviderGSVTTS(TTSProvider):
    REQUIRED_SYNTHESIS_PARAMS = (
        "ref_audio_path",
        "prompt_text",
        "prompt_lang",
        "text_lang",
    )

    def __init__(
        self,
        provider_config: dict,
        provider_settings: dict,
    ) -> None:
        super().__init__(provider_config, provider_settings)

        self.api_base = provider_config.get("api_base", "http://127.0.0.1:9880").rstrip(
            "/",
        )
        self.gpt_weights_path: str = provider_config.get("gpt_weights_path", "")
        self.sovits_weights_path: str = provider_config.get("sovits_weights_path", "")

        self.default_params = self._normalize_default_params(
            provider_config.get("gsv_default_parms", {}),
        )
        self.timeout = provider_config.get("timeout", 60)
        self._session: aiohttp.ClientSession | None = None

    @classmethod
    def _normalize_default_params(cls, raw_params: dict) -> dict:
        if not isinstance(raw_params, dict):
            return {}

        params = {}
        for raw_key, value in raw_params.items():
            key = str(raw_key or "").strip().removeprefix("gsv_")
            if not key:
                continue

            if key == "aux_ref_audio_paths":
                parsed = cls._parse_aux_ref_audio_paths(value)
                if parsed:
                    params[key] = parsed
                continue

            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue

            params[key] = value

        if "streaming_mode" in params and params["streaming_mode"]:
            logger.warning("[GSV TTS] Native streaming_mode is disabled in AstrBot v1")
        params["streaming_mode"] = False
        return params

    @staticmethod
    def _parse_aux_ref_audio_paths(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item or "").strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [
                        str(item).strip() for item in parsed if str(item or "").strip()
                    ]
            return [part.strip() for part in re.split(r"[\n;,]+", raw) if part.strip()]
        return [str(value).strip()] if str(value).strip() else []

    async def initialize(self) -> None:
        """异步初始化：在 ProviderManager 中被调用"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        )
        try:
            await self._set_model_weights()
            logger.info("[GSV TTS] 初始化完成")
        except Exception as e:
            logger.error(f"[GSV TTS] 初始化失败：{e}")
            raise

    def get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            raise RuntimeError(
                "[GSV TTS] Provider HTTP session is not ready or closed.",
            )
        return self._session

    async def _make_request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        params=None,
        json_payload=None,
        retries: int = 3,
    ) -> bytes | None:
        """发起请求"""
        for attempt in range(retries):
            logger.debug(
                f"[GSV TTS] 请求地址：{endpoint}，方法：{method}，参数：{params or json_payload}",
            )
            try:
                async with self.get_session().request(
                    method,
                    endpoint,
                    params=params,
                    json=json_payload,
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(
                            f"[GSV TTS] Request to {endpoint} failed with status {response.status}: {error_text}",
                        )
                    return await response.read()
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(
                        f"[GSV TTS] 请求 {endpoint} 第 {attempt + 1} 次失败：{e}，重试中...",
                    )
                    await asyncio.sleep(1)
                else:
                    logger.error(f"[GSV TTS] 请求 {endpoint} 最终失败：{e}")
                    raise

    async def _set_model_weights(self) -> None:
        """设置模型路径"""
        if self.gpt_weights_path:
            await self._make_request(
                f"{self.api_base}/set_gpt_weights",
                params={"weights_path": self.gpt_weights_path},
            )
            logger.info(f"[GSV TTS] 成功设置 GPT 模型路径：{self.gpt_weights_path}")
        else:
            logger.info("[GSV TTS] GPT 模型路径未配置，将使用内置 GPT 模型")

        if self.sovits_weights_path:
            await self._make_request(
                f"{self.api_base}/set_sovits_weights",
                params={"weights_path": self.sovits_weights_path},
            )
            logger.info(
                f"[GSV TTS] 成功设置 SoVITS 模型路径：{self.sovits_weights_path}",
            )
        else:
            logger.info("[GSV TTS] SoVITS 模型路径未配置，将使用内置 SoVITS 模型")

    async def get_audio(self, text: str) -> str:
        """实现 TTS 核心方法，根据文本内容自动切换情绪"""
        if not text.strip():
            raise ValueError("[GSV TTS] TTS 文本不能为空")

        endpoint = f"{self.api_base}/tts"

        params = self.build_synthesis_params(text)
        self._validate_synthesis_params(params)

        temp_dir = Path(get_astrbot_temp_path()) / "gsv_tts"
        temp_dir.mkdir(parents=True, exist_ok=True)
        media_type = str(params.get("media_type", "wav") or "wav").strip().lower()
        suffix = re.sub(r"[^a-z0-9]+", "", media_type) or "wav"
        path = temp_dir / f"gsv_tts_{uuid.uuid4().hex}.{suffix}"

        logger.debug(f"[GSV TTS] 正在调用语音合成接口，参数：{params}")

        result = await self._make_request(
            endpoint,
            method="POST",
            json_payload=params,
        )
        if isinstance(result, bytes):
            path.write_bytes(result)
            return str(path)
        raise Exception(f"[GSV TTS] 合成失败，输入文本：{text}，错误信息：{result}")

    def build_synthesis_params(self, text: str) -> dict:
        """构建语音合成所需的参数字典。

        当前仅包含默认参数 + 文本，未来可在此基础上动态添加如情绪、角色等语义控制字段。
        """
        params = self.default_params.copy()
        params["text"] = text
        return params

    def _validate_synthesis_params(self, params: dict) -> None:
        missing = [
            key
            for key in self.REQUIRED_SYNTHESIS_PARAMS
            if not str(params.get(key, "") or "").strip()
        ]
        if missing:
            raise ValueError(
                "[GSV TTS] Missing required GPT-SoVITS params: " + ", ".join(missing),
            )

    async def terminate(self) -> None:
        """终止释放资源：在 ProviderManager 中被调用"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("[GSV TTS] Session 已关闭")
