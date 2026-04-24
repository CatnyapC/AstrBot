import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from astrbot.core.message.components import Plain, Record
from astrbot.core.message.message_event_result import (
    MessageEventResult,
    ResultContentType,
)
from astrbot.core.platform.message_type import MessageType
from astrbot.core.provider.sources.gsv_selfhosted_source import ProviderGSVTTS


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: bytes = b"audio") -> None:
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")


class _RequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    closed = False

    def __init__(self, response: _FakeResponse | None = None) -> None:
        self.response = response or _FakeResponse()
        self.requests: list[dict] = []

    def request(self, method: str, endpoint: str, *, params=None, json=None):
        self.requests.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "json": json,
            }
        )
        return _RequestContext(self.response)


def _base_provider_config(**overrides):
    config = {
        "api_base": "http://gsv.local",
        "timeout": 3,
        "gsv_default_parms": {
            "gsv_ref_audio_path": "/voices/Ref Voice.WAV",
            "gsv_prompt_text": "Exact Prompt Text MiXed",
            "gsv_prompt_lang": "ZH",
            "gsv_text_lang": "ZH",
            "gsv_top_k": 5,
            "gsv_top_p": 0.9,
            "gsv_split_bucket": True,
            "gsv_aux_ref_audio_paths": "/voices/a.wav\n/voices/b.wav",
            "gsv_streaming_mode": True,
            "gsv_media_type": "wav",
            "gsv_empty_optional": "",
        },
    }
    config.update(overrides)
    return config


def test_gsv_payload_preserves_types_and_omits_empty_values():
    provider = ProviderGSVTTS(_base_provider_config(), {})

    params = provider.build_synthesis_params("Reply Text")

    assert params["text"] == "Reply Text"
    assert params["ref_audio_path"] == "/voices/Ref Voice.WAV"
    assert params["prompt_text"] == "Exact Prompt Text MiXed"
    assert params["prompt_lang"] == "ZH"
    assert params["text_lang"] == "ZH"
    assert params["top_k"] == 5
    assert params["top_p"] == 0.9
    assert params["split_bucket"] is True
    assert params["aux_ref_audio_paths"] == ["/voices/a.wav", "/voices/b.wav"]
    assert params["streaming_mode"] is False
    assert "empty_optional" not in params


def test_gsv_local_reference_path_validation_fails_before_request():
    provider = ProviderGSVTTS(
        _base_provider_config(api_base="http://127.0.0.1:9880"), {}
    )
    params = provider.build_synthesis_params("hello")

    with pytest.raises(ValueError, match="ref_audio_path does not exist"):
        provider._validate_synthesis_params(params)


@pytest.mark.asyncio
async def test_gsv_get_audio_requires_reference_fields():
    provider = ProviderGSVTTS(
        _base_provider_config(
            gsv_default_parms={
                "gsv_prompt_text": "prompt",
                "gsv_prompt_lang": "zh",
                "gsv_text_lang": "zh",
            }
        ),
        {},
    )

    with pytest.raises(ValueError, match="ref_audio_path"):
        await provider.get_audio("hello")


@pytest.mark.asyncio
async def test_gsv_get_audio_posts_json_and_writes_media_file(tmp_path):
    ref_audio_path = tmp_path / "ref.wav"
    ref_audio_path.write_bytes(b"ref")
    provider = ProviderGSVTTS(
        _base_provider_config(
            gsv_default_parms={
                **_base_provider_config()["gsv_default_parms"],
                "gsv_ref_audio_path": str(ref_audio_path),
                "gsv_aux_ref_audio_paths": "",
            },
        ),
        {},
    )
    session = _FakeSession(_FakeResponse(body=b"wav-data"))
    provider._session = session

    with patch(
        "astrbot.core.provider.sources.gsv_selfhosted_source.get_astrbot_temp_path",
        return_value=str(tmp_path),
    ):
        audio_path = await provider.get_audio("hello")

    path = Path(audio_path)
    assert path.read_bytes() == b"wav-data"
    assert path.parent == tmp_path / "gsv_tts"
    assert path.suffix == ".wav"
    assert session.requests == [
        {
            "method": "POST",
            "endpoint": "http://gsv.local/tts",
            "params": None,
            "json": provider.build_synthesis_params("hello"),
        }
    ]


@pytest.mark.asyncio
async def test_gsv_weight_endpoints_only_called_when_paths_set():
    provider = ProviderGSVTTS(_base_provider_config(), {})
    provider._make_request = AsyncMock(return_value=b"success")

    await provider._set_model_weights()

    provider._make_request.assert_not_awaited()

    provider = ProviderGSVTTS(
        _base_provider_config(
            gpt_weights_path="/models/gpt.ckpt",
            sovits_weights_path="/models/sovits.pth",
        ),
        {},
    )
    provider._make_request = AsyncMock(return_value=b"success")

    await provider._set_model_weights()

    assert provider._make_request.await_args_list[0].kwargs == {
        "params": {"weights_path": "/models/gpt.ckpt"}
    }
    assert provider._make_request.await_args_list[0].args == (
        "http://gsv.local/set_gpt_weights",
    )
    assert provider._make_request.await_args_list[1].kwargs == {
        "params": {"weights_path": "/models/sovits.pth"}
    }
    assert provider._make_request.await_args_list[1].args == (
        "http://gsv.local/set_sovits_weights",
    )


@pytest.mark.asyncio
async def test_gsv_weight_setup_failure_propagates_when_configured():
    provider = ProviderGSVTTS(
        _base_provider_config(gpt_weights_path="/models/gpt.ckpt"),
        {},
    )
    provider._make_request = AsyncMock(side_effect=RuntimeError("bad weights"))

    with pytest.raises(RuntimeError, match="bad weights"):
        await provider._set_model_weights()


class _FakePluginContext:
    def __init__(self, provider) -> None:
        self.provider = provider

    def get_using_tts_provider(self, umo):
        del umo
        return self.provider


class _FakeCtx:
    def __init__(self, *, enable_tts: bool, provider) -> None:
        self.astrbot_config = {
            "provider_tts_settings": {
                "enable": enable_tts,
                "dual_output": False,
                "use_file_service": False,
                "trigger_probability": 1.0,
            },
            "callback_api_base": "",
            "t2i": False,
        }
        self.plugin_manager = type(
            "PluginManager",
            (),
            {"context": _FakePluginContext(provider)},
        )()


class _FakeEvent:
    unified_msg_origin = "umo"
    plugins_name = []

    def __init__(self, result) -> None:
        self._result = result
        self.message_obj = type("Message", (), {"message_id": "raw1"})()
        self.extras = {}

    def get_result(self):
        return self._result

    def get_platform_name(self):
        return "aiocqhttp"

    def get_message_type(self):
        return MessageType.FRIEND_MESSAGE

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def is_stopped(self):
        return False

    def get_self_id(self):
        return "bot"

    def get_sender_id(self):
        return "user"

    def get_sender_name(self):
        return "user"


class _FakeTTSProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_audio(self, text: str) -> str:
        self.calls.append(text)
        return "/tmp/gsv.wav"


def _load_result_stage_module(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    module_name = "astrbot.core.pipeline.result_decorate.stage"

    for name in (
        module_name,
        "astrbot.core.pipeline",
        "astrbot.core.pipeline.context",
        "astrbot.core.pipeline.stage",
        "astrbot.core.pipeline.result_decorate",
        "astrbot.core.pipeline.content_safety_check",
        "astrbot.core.pipeline.content_safety_check.stage",
        "astrbot.core.platform.astr_message_event",
        "astrbot.core.star.session_llm_manager",
        "astrbot.core.star.star",
        "astrbot.core.star.star_handler",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    pipeline_pkg = types.ModuleType("astrbot.core.pipeline")
    pipeline_pkg.__path__ = [str(root / "astrbot" / "core" / "pipeline")]
    result_pkg = types.ModuleType("astrbot.core.pipeline.result_decorate")
    result_pkg.__path__ = [
        str(root / "astrbot" / "core" / "pipeline" / "result_decorate")
    ]
    safety_pkg = types.ModuleType("astrbot.core.pipeline.content_safety_check")
    safety_pkg.__path__ = [
        str(root / "astrbot" / "core" / "pipeline" / "content_safety_check")
    ]
    context_mod = types.ModuleType("astrbot.core.pipeline.context")
    stage_mod = types.ModuleType("astrbot.core.pipeline.stage")
    safety_stage_mod = types.ModuleType(
        "astrbot.core.pipeline.content_safety_check.stage",
    )
    event_mod = types.ModuleType("astrbot.core.platform.astr_message_event")
    session_mod = types.ModuleType("astrbot.core.star.session_llm_manager")
    star_mod = types.ModuleType("astrbot.core.star.star")
    handler_mod = types.ModuleType("astrbot.core.star.star_handler")

    class PipelineContext:
        pass

    class Stage:
        pass

    class ContentSafetyCheckStage:
        pass

    class AstrMessageEvent:
        pass

    class SessionServiceManager:
        @staticmethod
        async def should_process_tts_request(event):
            del event
            return False

    class EventType:
        OnDecoratingResultEvent = "on_decorating_result"

    class _Registry:
        @staticmethod
        def get_handlers_by_event_type(*args, **kwargs):
            del args, kwargs
            return []

    context_mod.PipelineContext = PipelineContext
    stage_mod.Stage = Stage
    stage_mod.register_stage = lambda cls: cls
    stage_mod.registered_stages = []
    safety_stage_mod.ContentSafetyCheckStage = ContentSafetyCheckStage
    event_mod.AstrMessageEvent = AstrMessageEvent
    session_mod.SessionServiceManager = SessionServiceManager
    star_mod.star_map = {}
    handler_mod.EventType = EventType
    handler_mod.star_handlers_registry = _Registry()

    monkeypatch.setitem(sys.modules, "astrbot.core.pipeline", pipeline_pkg)
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.pipeline.result_decorate",
        result_pkg,
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.pipeline.content_safety_check",
        safety_pkg,
    )
    monkeypatch.setitem(sys.modules, "astrbot.core.pipeline.context", context_mod)
    monkeypatch.setitem(sys.modules, "astrbot.core.pipeline.stage", stage_mod)
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.pipeline.content_safety_check.stage",
        safety_stage_mod,
    )
    monkeypatch.setitem(
        sys.modules, "astrbot.core.platform.astr_message_event", event_mod
    )
    monkeypatch.setitem(
        sys.modules, "astrbot.core.star.session_llm_manager", session_mod
    )
    monkeypatch.setitem(sys.modules, "astrbot.core.star.star", star_mod)
    monkeypatch.setitem(sys.modules, "astrbot.core.star.star_handler", handler_mod)

    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "astrbot" / "core" / "pipeline" / "result_decorate" / "stage.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _make_stage(stage_cls, *, enable_tts: bool, provider):
    stage = stage_cls()
    stage.ctx = _FakeCtx(enable_tts=enable_tts, provider=provider)
    stage.reply_prefix = ""
    stage.reply_with_mention = False
    stage.reply_with_quote = False
    stage.content_safe_check_reply = False
    stage.content_safe_check_stage = None
    stage.enable_segmented_reply = False
    stage.tts_trigger_probability = 1.0
    stage.show_reasoning = False
    stage.forward_threshold = 9999
    stage.t2i_word_threshold = 9999
    return stage


async def _drain_stage(stage, event: _FakeEvent) -> None:
    async for _ in stage.process(event):
        pass


@pytest.mark.asyncio
async def test_result_decorate_master_switch_off_skips_tts(monkeypatch):
    result_stage_mod = _load_result_stage_module(monkeypatch)
    provider = _FakeTTSProvider()
    stage = _make_stage(
        result_stage_mod.ResultDecorateStage,
        enable_tts=False,
        provider=provider,
    )
    result = MessageEventResult(
        chain=[Plain("hello")],
        result_content_type=ResultContentType.LLM_RESULT,
    )
    event = _FakeEvent(result)
    monkeypatch.setattr(
        result_stage_mod.star_handlers_registry,
        "get_handlers_by_event_type",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        result_stage_mod.SessionServiceManager,
        "should_process_tts_request",
        AsyncMock(return_value=True),
    )

    await _drain_stage(stage, event)

    assert provider.calls == []
    assert isinstance(result.chain[0], Plain)


@pytest.mark.asyncio
async def test_result_decorate_tts_emits_record_when_enabled(monkeypatch):
    result_stage_mod = _load_result_stage_module(monkeypatch)
    provider = _FakeTTSProvider()
    stage = _make_stage(
        result_stage_mod.ResultDecorateStage,
        enable_tts=True,
        provider=provider,
    )
    result = MessageEventResult(
        chain=[Plain("hello")],
        result_content_type=ResultContentType.LLM_RESULT,
    )
    event = _FakeEvent(result)
    monkeypatch.setattr(
        result_stage_mod.star_handlers_registry,
        "get_handlers_by_event_type",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        result_stage_mod.SessionServiceManager,
        "should_process_tts_request",
        AsyncMock(return_value=True),
    )

    await _drain_stage(stage, event)

    assert provider.calls == ["hello"]
    assert len(result.chain) == 1
    assert isinstance(result.chain[0], Record)
    assert result.chain[0].file == "/tmp/gsv.wav"


@pytest.mark.asyncio
async def test_result_decorate_tts_failure_falls_back_to_text(monkeypatch):
    result_stage_mod = _load_result_stage_module(monkeypatch)

    class _FailingProvider:
        async def get_audio(self, text: str) -> str:
            del text
            raise RuntimeError("tts failed")

    stage = _make_stage(
        result_stage_mod.ResultDecorateStage,
        enable_tts=True,
        provider=_FailingProvider(),
    )
    result = MessageEventResult(
        chain=[Plain("hello")],
        result_content_type=ResultContentType.LLM_RESULT,
    )
    event = _FakeEvent(result)
    monkeypatch.setattr(
        result_stage_mod.star_handlers_registry,
        "get_handlers_by_event_type",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        result_stage_mod.SessionServiceManager,
        "should_process_tts_request",
        AsyncMock(return_value=True),
    )

    await _drain_stage(stage, event)

    assert len(result.chain) == 1
    assert isinstance(result.chain[0], Plain)
    assert result.chain[0].text == "hello"
