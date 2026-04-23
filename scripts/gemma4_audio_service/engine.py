from __future__ import annotations

import base64
import binascii
import contextlib
import logging
import math
import mimetypes
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_AUDIO_PROMPT = (
    "你正在处理一段已经附加到本请求中的音频。请先尽量逐字转写其中的人声，"
    "再用一句简洁中文概括主要内容、说话人情绪和关键环境音。"
    "背景线索：机器人/被呼唤对象名叫“狐米”。如果听到接近 hu mi、humi、胡米、呼米、狐咪、狐弥 的发音，"
    "在转写和概括中统一写作“狐米”，不要写同音词或相似字。"
    "即使音质差也要根据可听内容给出最可能转写；只有完全没有可辨认人声或全是噪声/静音时才回答听不清。"
    "输出格式：转写：...；概括：...。"
    "禁止要求补交材料。"
)
DEFAULT_MODEL_ID = "google/gemma-4-e2b-it"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4010
DEFAULT_MIN_AUDIO_SECONDS = 4.0

logger = logging.getLogger(__name__)


class ServiceConfigError(RuntimeError):
    """Raised when service configuration is invalid."""


class AudioInputError(RuntimeError):
    """Raised when audio input is invalid."""


class ModelLoadError(RuntimeError):
    """Raised when the model cannot be loaded."""


@dataclass(slots=True, frozen=True)
class ServiceConfig:
    model_id: str = DEFAULT_MODEL_ID
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    device: str = "auto"
    use_metal_quantization: bool = False
    quant_bits: int = 4
    quant_group_size: int = 64
    default_prompt: str = DEFAULT_AUDIO_PROMPT
    default_max_new_tokens: int = 192
    min_audio_seconds: float = DEFAULT_MIN_AUDIO_SECONDS
    attn_implementation: str = "sdpa"
    trust_remote_code: bool = False
    temp_dir: str = ""
    allow_cpu_fallback_on_mps_buffer_error: bool = True

    @classmethod
    def from_env(cls) -> ServiceConfig:
        return cls(
            model_id=os.getenv("GEMMA4_AUDIO_MODEL_ID", DEFAULT_MODEL_ID).strip()
            or DEFAULT_MODEL_ID,
            host=os.getenv("GEMMA4_AUDIO_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=_parse_int_env("GEMMA4_AUDIO_PORT", DEFAULT_PORT, min_value=1),
            device=os.getenv("GEMMA4_AUDIO_DEVICE", "auto").strip().lower() or "auto",
            use_metal_quantization=_parse_bool_env(
                "GEMMA4_AUDIO_USE_METAL_QUANTIZATION", False
            ),
            quant_bits=_parse_int_env(
                "GEMMA4_AUDIO_QUANT_BITS", 4, allowed_values={2, 4, 8}
            ),
            quant_group_size=_parse_int_env(
                "GEMMA4_AUDIO_QUANT_GROUP_SIZE", 64, min_value=1
            ),
            default_prompt=os.getenv(
                "GEMMA4_AUDIO_DEFAULT_PROMPT", DEFAULT_AUDIO_PROMPT
            ).strip()
            or DEFAULT_AUDIO_PROMPT,
            default_max_new_tokens=_parse_int_env(
                "GEMMA4_AUDIO_DEFAULT_MAX_NEW_TOKENS", 192, min_value=1
            ),
            min_audio_seconds=_parse_float_env(
                "GEMMA4_AUDIO_MIN_SECONDS", DEFAULT_MIN_AUDIO_SECONDS, min_value=0.0
            ),
            attn_implementation=os.getenv(
                "GEMMA4_AUDIO_ATTN_IMPLEMENTATION", "sdpa"
            ).strip()
            or "sdpa",
            trust_remote_code=_parse_bool_env("GEMMA4_AUDIO_TRUST_REMOTE_CODE", False),
            temp_dir=os.getenv("GEMMA4_AUDIO_TEMP_DIR", "").strip(),
            allow_cpu_fallback_on_mps_buffer_error=_parse_bool_env(
                "GEMMA4_AUDIO_ALLOW_CPU_FALLBACK_ON_MPS_BUFFER_ERROR", True
            ),
        )


@dataclass(slots=True, frozen=True)
class ResolvedAudioInput:
    path: str
    cleanup_path: str = ""
    format_hint: str = "wav"
    mime_type: str = "audio/wav"
    duration_seconds: float | None = None
    extended_from_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class InferenceRequest:
    prompt: str
    audio_path: str = ""
    audio_url: str = ""
    audio_base64: str = ""
    audio_format: str = "wav"
    max_new_tokens: int = 192
    temperature: float = 0.0
    top_p: float = 1.0
    do_sample: bool = False


@dataclass(slots=True, frozen=True)
class InferenceResult:
    text: str
    model: str
    device: str
    prompt: str
    duration_seconds: float | None
    load_seconds: float
    inference_seconds: float
    quantization: str


@dataclass(slots=True, frozen=True)
class ParsedChatRequest:
    prompt: str
    audio_path: str = ""
    audio_url: str = ""
    audio_base64: str = ""
    audio_format: str = "wav"


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ServiceConfigError(f"invalid boolean env: {name}={raw}")


def _parse_int_env(
    name: str,
    default: int,
    *,
    min_value: int | None = None,
    allowed_values: set[int] | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ServiceConfigError(f"invalid integer env: {name}={raw}") from exc
    if min_value is not None and value < min_value:
        raise ServiceConfigError(f"{name} must be >= {min_value}")
    if allowed_values is not None and value not in allowed_values:
        raise ServiceConfigError(f"{name} must be one of {sorted(allowed_values)}")
    return value


def _parse_float_env(
    name: str, default: float, *, min_value: float | None = None
) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ServiceConfigError(f"invalid float env: {name}={raw}") from exc
    if min_value is not None and value < min_value:
        raise ServiceConfigError(f"{name} must be >= {min_value}")
    return value


def decode_base64_audio(data: str) -> bytes:
    value = str(data or "").strip()
    if not value:
        raise AudioInputError("empty audio_base64")
    if value.startswith("data:") and ";base64," in value:
        value = value.split(";base64,", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AudioInputError("invalid audio_base64") from exc


def guess_suffix_from_format(format_hint: str, mime_type: str = "") -> str:
    fmt = str(format_hint or "").strip().lower()
    if fmt:
        if not fmt.startswith("."):
            return f".{fmt}"
        return fmt
    guessed = mimetypes.guess_extension(mime_type or "")
    if guessed:
        return guessed
    return ".wav"


def extract_prompt_and_audio_from_messages(
    messages: list[dict[str, Any]],
) -> ParsedChatRequest:
    system_parts: list[str] = []
    user_parts: list[str] = []
    audio_path = ""
    audio_url = ""
    audio_base64 = ""
    audio_format = "wav"
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content")
        text_parts: list[str] = []
        if isinstance(content, str):
            if content.strip():
                text_parts.append(content.strip())
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
                    continue
                if block_type == "audio":
                    value = str(
                        block.get("path")
                        or block.get("audio")
                        or block.get("url")
                        or ""
                    ).strip()
                    if value:
                        local_path = _normalize_local_audio_path(value)
                        if local_path:
                            audio_path = local_path
                        else:
                            audio_url = value
                    continue
                if block_type == "audio_url":
                    audio_obj = block.get("audio_url")
                    if isinstance(audio_obj, dict):
                        value = str(audio_obj.get("url") or "").strip()
                        if value:
                            local_path = _normalize_local_audio_path(value)
                            if local_path:
                                audio_path = local_path
                            else:
                                audio_url = value
                    continue
                if block_type == "input_audio":
                    audio_obj = block.get("input_audio")
                    if isinstance(audio_obj, dict):
                        data = str(audio_obj.get("data") or "").strip()
                        if data:
                            audio_base64 = data
                        audio_format = (
                            str(audio_obj.get("format") or "").strip().lower() or "wav"
                        )
        if role == "system" and text_parts:
            system_parts.append("\n".join(text_parts))
        elif role == "user" and text_parts:
            user_parts.append("\n".join(text_parts))
    prompt_parts = [*system_parts, *user_parts]
    prompt = "\n\n".join(part for part in prompt_parts if part).strip()
    return ParsedChatRequest(
        prompt=prompt,
        audio_path=audio_path,
        audio_url=audio_url,
        audio_base64=audio_base64,
        audio_format=audio_format,
    )


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if value.startswith("file://"):
        return True
    if value.startswith("/"):
        return True
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in {"http", "https", "data"}:
        return False
    return Path(value).exists()


def _normalize_local_audio_path(value: str) -> str:
    if not _looks_like_path(value):
        return ""
    if value.startswith("file://"):
        parsed = urllib.parse.urlparse(value)
        return urllib.request.url2pathname(parsed.path)
    return value


def _shape_of(value: Any) -> str:
    shape = getattr(value, "shape", None)
    if shape is None:
        return ""
    return "x".join(str(part) for part in shape)


def _inspect_wav_signal(path: str) -> dict[str, Any]:
    if Path(path).suffix.lower() != ".wav":
        return {}
    try:
        with wave.open(path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.getnframes()
            raw = wav_file.readframes(frames)
    except Exception:
        return {}

    stats: dict[str, Any] = {
        "channels": channels,
        "sample_width": sample_width,
        "sample_rate": sample_rate,
        "frames": frames,
    }
    if not raw:
        return stats

    samples: list[int]
    full_scale: float
    if sample_width == 1:
        samples = [byte - 128 for byte in raw]
        full_scale = 128.0
    elif sample_width == 2:
        values = array("h")
        values.frombytes(raw)
        samples = list(values)
        full_scale = 32768.0
    elif sample_width == 4:
        values = array("i")
        values.frombytes(raw)
        samples = list(values)
        full_scale = 2147483648.0
    else:
        return stats

    if not samples:
        return stats
    peak = max(abs(sample) for sample in samples)
    rms = math.sqrt(
        sum(float(sample) * float(sample) for sample in samples) / len(samples)
    )
    stats["peak_dbfs"] = round(20 * math.log10(max(peak, 1) / full_scale), 1)
    stats["rms_dbfs"] = round(20 * math.log10(max(rms, 1.0) / full_scale), 1)
    return stats


def _extend_short_wav_input(
    audio: ResolvedAudioInput,
    *,
    min_seconds: float,
    temp_dir: str,
) -> ResolvedAudioInput:
    if min_seconds <= 0 or Path(audio.path).suffix.lower() != ".wav":
        return audio
    try:
        with wave.open(audio.path, "rb") as wav_file:
            params = wav_file.getparams()
            frames = wav_file.readframes(params.nframes)
    except Exception:
        return audio
    if params.framerate <= 0:
        return audio
    duration = params.nframes / float(params.framerate)
    if duration >= min_seconds:
        return audio
    pad_frames = max(1, math.ceil((min_seconds - duration) * params.framerate))
    silence = b"\x00" * pad_frames * params.nchannels * params.sampwidth
    output_dir = Path(temp_dir.strip() or tempfile.gettempdir())
    output_dir.mkdir(parents=True, exist_ok=True)
    extended_path = output_dir / f"gemma4-audio-extended-{uuid.uuid4().hex}.wav"
    with wave.open(str(extended_path), "wb") as wav_file:
        wav_file.setparams(params)
        wav_file.writeframes(frames + silence)
    logger.warning(
        "Gemma4 audio extended short wav with trailing silence: original_seconds=%.2f extended_seconds=%.2f path=%s",
        duration,
        min_seconds,
        extended_path,
    )
    return ResolvedAudioInput(
        path=str(extended_path),
        cleanup_path=str(extended_path),
        format_hint=audio.format_hint,
        mime_type=audio.mime_type,
        duration_seconds=min_seconds,
        extended_from_seconds=duration,
    )


def _trim_repeated_completion_tail(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value

    trimmed = _trim_repeated_suffix_unit(value)
    if trimmed != value:
        logger.warning(
            "Gemma4 audio trimmed repeated completion tail: before=%r after=%r",
            value[:500],
            trimmed[:500],
        )
    return trimmed


def _trim_repeated_suffix_unit(text: str) -> str:
    value = text.rstrip()
    punctuation = "，。！？!?、；;：:,. "
    min_repeats = 6
    max_unit_len = min(12, max(1, len(value) // min_repeats))
    for unit_len in range(1, max_unit_len + 1):
        unit = value[-unit_len:]
        if not unit.strip(punctuation):
            continue
        count = 0
        pos = len(value)
        while pos >= unit_len and value[pos - unit_len : pos] == unit:
            count += 1
            pos -= unit_len
        if count < min_repeats:
            continue
        prefix = value[: pos + unit_len].rstrip()
        if prefix and prefix[-1] not in punctuation:
            prefix += "…"
        return prefix
    return value


class Gemma4AudioEngine:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._processor = None
        self._model = None
        self._device = "cpu"
        self._quantization = "none"
        self._load_seconds = 0.0
        self._disable_metal_quantization_runtime = not config.use_metal_quantization

    @property
    def model_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    def inspect(self) -> dict[str, Any]:
        return {
            "model_id": self.config.model_id,
            "model_loaded": self.model_loaded,
            "device": self._device,
            "quantization": self._quantization,
            "load_seconds": self._load_seconds,
            "metal_quantization_enabled": not self._disable_metal_quantization_runtime,
        }

    def analyze(self, request: InferenceRequest) -> InferenceResult:
        prompt = str(request.prompt or "").strip() or self.config.default_prompt
        resolved_audio = self._resolve_audio_input(request)
        cleanup_paths = [resolved_audio.cleanup_path.strip()]
        try:
            resolved_audio = _extend_short_wav_input(
                resolved_audio,
                min_seconds=self.config.min_audio_seconds,
                temp_dir=self.config.temp_dir,
            )
            cleanup_paths.append(resolved_audio.cleanup_path.strip())
            self._ensure_loaded()
            audio_signal = _inspect_wav_signal(resolved_audio.path)
            logger.warning(
                "Gemma4 audio inference start: device=%s audio=%s duration=%s rate=%s channels=%s rms_dbfs=%s peak_dbfs=%s max_new_tokens=%s",
                self._device,
                resolved_audio.path,
                resolved_audio.duration_seconds,
                audio_signal.get("sample_rate", ""),
                audio_signal.get("channels", ""),
                audio_signal.get("rms_dbfs", ""),
                audio_signal.get("peak_dbfs", ""),
                request.max_new_tokens or self.config.default_max_new_tokens,
            )
            inference_started = time.perf_counter()
            text = self._generate_text(
                prompt=prompt,
                audio_path=resolved_audio.path,
                max_new_tokens=request.max_new_tokens
                or self.config.default_max_new_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                do_sample=request.do_sample,
            )
            if resolved_audio.extended_from_seconds is not None:
                text = _trim_repeated_completion_tail(text)
            inference_seconds = time.perf_counter() - inference_started
            return InferenceResult(
                text=text.strip(),
                model=self.config.model_id,
                device=self._device,
                prompt=prompt,
                duration_seconds=resolved_audio.duration_seconds,
                load_seconds=self._load_seconds,
                inference_seconds=inference_seconds,
                quantization=self._quantization,
            )
        finally:
            for cleanup_path in {path for path in cleanup_paths if path}:
                with contextlib.suppress(Exception):
                    Path(cleanup_path).unlink(missing_ok=True)

    def _ensure_loaded(self) -> None:
        if self.model_loaded:
            return
        with self._lock:
            if self.model_loaded:
                return
            started = time.perf_counter()
            self._processor, self._model, self._device, self._quantization = (
                self._load_model_and_processor()
            )
            self._load_seconds = time.perf_counter() - started

    def _load_model_and_processor(self):
        try:
            import torch
            from transformers import AutoProcessor
        except Exception as exc:
            raise ModelLoadError(
                "missing runtime dependencies; install requirements.txt for gemma4_audio_service"
            ) from exc
        model_cls = None
        try:
            from transformers import Gemma4ForConditionalGeneration

            model_cls = Gemma4ForConditionalGeneration
        except Exception:
            try:
                from transformers import AutoModelForImageTextToText

                model_cls = AutoModelForImageTextToText
            except Exception as exc:
                raise ModelLoadError(
                    "no Gemma 4 multimodal model class available"
                ) from exc

        device = self._pick_device(torch)
        processor = AutoProcessor.from_pretrained(
            self.config.model_id,
            padding_side="left",
            trust_remote_code=self.config.trust_remote_code,
        )
        kwargs: dict[str, Any] = {
            "trust_remote_code": self.config.trust_remote_code,
            "low_cpu_mem_usage": True,
        }
        quantization = "none"
        if device == "mps":
            kwargs["torch_dtype"] = torch.float16
            kwargs["attn_implementation"] = self.config.attn_implementation
            if (
                self.config.use_metal_quantization
                and not self._disable_metal_quantization_runtime
            ):
                try:
                    from transformers import MetalConfig

                    kwargs["quantization_config"] = MetalConfig(
                        bits=self.config.quant_bits,
                        group_size=self.config.quant_group_size,
                    )
                    kwargs["device_map"] = "mps"
                    quantization = f"metal-{self.config.quant_bits}bit"
                except Exception:
                    kwargs["device_map"] = "mps"
            else:
                kwargs["device_map"] = "mps"
        else:
            kwargs["torch_dtype"] = torch.float32

        try:
            model = model_cls.from_pretrained(self.config.model_id, **kwargs)
        except TypeError:
            kwargs.pop("attn_implementation", None)
            model = model_cls.from_pretrained(self.config.model_id, **kwargs)
        except Exception as exc:
            if (
                device == "mps"
                and self.config.allow_cpu_fallback_on_mps_buffer_error
                and _is_mps_buffer_size_error(exc)
            ):
                logger.warning(
                    "Gemma4 audio MPS load hit buffer-size limit; retrying on CPU. err=%s",
                    exc,
                )
                cpu_kwargs: dict[str, Any] = {
                    "trust_remote_code": self.config.trust_remote_code,
                    "low_cpu_mem_usage": True,
                    "torch_dtype": torch.float32,
                }
                try:
                    model = model_cls.from_pretrained(
                        self.config.model_id, **cpu_kwargs
                    )
                    device = "cpu"
                    quantization = "none"
                except Exception as cpu_exc:
                    raise ModelLoadError(
                        f"failed to load model {self.config.model_id}: {cpu_exc}"
                    ) from cpu_exc
            else:
                raise ModelLoadError(
                    f"failed to load model {self.config.model_id}: {exc}"
                ) from exc

        if device != "mps":
            model = model.to(device)
        model.eval()
        return processor, model, device, quantization

    def _pick_device(self, torch_module) -> str:
        requested = self.config.device
        if requested and requested != "auto":
            return requested
        if (
            getattr(torch_module.backends, "mps", None)
            and torch_module.backends.mps.is_available()
        ):
            return "mps"
        return "cpu"

    def _generate_text(
        self,
        *,
        prompt: str,
        audio_path: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        do_sample: bool,
    ) -> str:
        import torch

        messages = self._build_messages(prompt=prompt, audio_path=audio_path)
        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            add_generation_prompt=True,
        )
        moved_inputs = self._move_processor_inputs(inputs, torch)
        input_len = 0
        input_ids = moved_inputs.get("input_ids")
        if input_ids is not None and hasattr(input_ids, "shape"):
            input_len = int(input_ids.shape[-1])
        input_features_shape = _shape_of(moved_inputs.get("input_features"))
        input_features_mask_shape = _shape_of(moved_inputs.get("input_features_mask"))
        if not input_features_shape:
            logger.warning(
                "Gemma4 audio processor produced no input_features: keys=%s",
                sorted(moved_inputs.keys()),
            )
        generation_kwargs = {
            "max_new_tokens": max(1, int(max_new_tokens)),
            "do_sample": bool(do_sample or temperature > 0.0),
        }
        if generation_kwargs["do_sample"]:
            generation_kwargs["temperature"] = max(0.01, float(temperature or 0.0))
            generation_kwargs["top_p"] = min(1.0, max(0.01, float(top_p or 1.0)))
        logger.warning(
            "Gemma4 audio generation begin: device=%s input_tokens=%s audio_features=%s audio_mask=%s do_sample=%s max_new_tokens=%s",
            self._device,
            input_len,
            input_features_shape,
            input_features_mask_shape,
            generation_kwargs["do_sample"],
            generation_kwargs["max_new_tokens"],
        )
        with torch.inference_mode():
            try:
                output = self._model.generate(**moved_inputs, **generation_kwargs)
            except ImportError as exc:
                if (
                    self._device == "mps"
                    and self._quantization.startswith("metal-")
                    and _is_metal_quant_kernel_error(exc)
                ):
                    logger.warning(
                        "Gemma4 audio metal quant kernel unavailable; reloading without metal quantization. err=%s",
                        exc,
                    )
                    self._reload_without_metal_quantization()
                    moved_inputs = self._move_processor_inputs(inputs, torch)
                    output = self._model.generate(**moved_inputs, **generation_kwargs)
                else:
                    raise
        logger.warning("Gemma4 audio generation finished: device=%s", self._device)
        completion = self._processor.decode(
            output[0][input_len:],
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()
        logger.warning("Gemma4 audio raw completion: %r", completion[:500])
        return completion

    def _build_messages(self, *, prompt: str, audio_path: str) -> list[dict[str, Any]]:
        normalized_audio_path = str(Path(audio_path).expanduser().resolve())
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "audio", "path": normalized_audio_path},
                ],
            }
        ]

    def _move_processor_inputs(self, inputs, torch_module) -> dict[str, Any]:
        model_dtype = getattr(self._model, "dtype", None)
        moved_inputs: dict[str, Any] = {}
        for key, value in dict(inputs).items():
            if not hasattr(value, "to"):
                moved_inputs[key] = value
                continue
            if model_dtype is not None and torch_module.is_floating_point(value):
                moved_inputs[key] = value.to(device=self._device, dtype=model_dtype)
            else:
                moved_inputs[key] = value.to(device=self._device)
        return moved_inputs

    def _reload_without_metal_quantization(self) -> None:
        with self._lock:
            self._disable_metal_quantization_runtime = True
            self._model = None
            self._processor = None
            self._device = "cpu"
            self._quantization = "none"
        self._ensure_loaded()

    def _resolve_audio_input(self, request: InferenceRequest) -> ResolvedAudioInput:
        if request.audio_path:
            return self._resolve_audio_path(request.audio_path)
        if request.audio_url:
            return self._resolve_audio_url(request.audio_url)
        if request.audio_base64:
            raw = decode_base64_audio(request.audio_base64)
            suffix = guess_suffix_from_format(request.audio_format)
            path = self._write_temp_audio(raw, suffix)
            return ResolvedAudioInput(
                path=path,
                cleanup_path=path,
                format_hint=request.audio_format or suffix.removeprefix("."),
                mime_type=mimetypes.guess_type(path)[0] or "audio/wav",
                duration_seconds=_read_wav_duration_seconds(path),
            )
        raise AudioInputError("missing audio input")

    def _resolve_audio_path(self, value: str) -> ResolvedAudioInput:
        path_value = str(value or "").strip()
        if path_value.startswith("file://"):
            parsed = urllib.parse.urlparse(path_value)
            path_value = urllib.request.url2pathname(parsed.path)
        if not path_value:
            raise AudioInputError("empty audio_path")
        path = Path(path_value).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise AudioInputError(f"audio_path not found: {path}")
        return ResolvedAudioInput(
            path=str(path),
            format_hint=path.suffix.removeprefix(".") or "wav",
            mime_type=mimetypes.guess_type(str(path))[0] or "audio/wav",
            duration_seconds=_read_wav_duration_seconds(str(path)),
        )

    def _resolve_audio_url(self, value: str) -> ResolvedAudioInput:
        raw = str(value or "").strip()
        if not raw:
            raise AudioInputError("empty audio_url")
        if raw.startswith("data:") and ";base64," in raw:
            header, encoded = raw.split(",", 1)
            mime_type = header.split(":", 1)[1].split(";", 1)[0]
            data = decode_base64_audio(encoded)
            path = self._write_temp_audio(data, guess_suffix_from_format("", mime_type))
            return ResolvedAudioInput(
                path=path,
                cleanup_path=path,
                format_hint=Path(path).suffix.removeprefix(".") or "wav",
                mime_type=mime_type or "audio/wav",
                duration_seconds=_read_wav_duration_seconds(path),
            )
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            with urllib.request.urlopen(raw) as response:
                data = response.read()
                mime_type = response.headers.get_content_type() or "audio/wav"
            path = self._write_temp_audio(data, guess_suffix_from_format("", mime_type))
            return ResolvedAudioInput(
                path=path,
                cleanup_path=path,
                format_hint=Path(path).suffix.removeprefix(".") or "wav",
                mime_type=mime_type,
                duration_seconds=_read_wav_duration_seconds(path),
            )
        return self._resolve_audio_path(raw)

    def _write_temp_audio(self, data: bytes, suffix: str) -> str:
        temp_dir = self.config.temp_dir.strip() or tempfile.gettempdir()
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        path = Path(temp_dir) / f"gemma4-audio-{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        return str(path)


def _read_wav_duration_seconds(path: str) -> float | None:
    suffix = Path(path).suffix.lower()
    if suffix != ".wav":
        return None
    try:
        with wave.open(path, "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
    except Exception:
        return None
    if rate <= 0:
        return None
    return frames / float(rate)


def _is_mps_buffer_size_error(exc: Exception) -> bool:
    return "invalid buffer size" in str(exc or "").lower()


def _is_metal_quant_kernel_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "quantization-mlx kernel" in text or "mlx-quantization-metal-kernels" in text
