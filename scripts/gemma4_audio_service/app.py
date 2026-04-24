from __future__ import annotations

import base64
import logging
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from .engine import (
    DEFAULT_AUDIO_PROMPT,
    AudioInputError,
    Gemma4AudioEngine,
    InferenceRequest,
    ModelLoadError,
    ServiceConfig,
    ServiceConfigError,
    extract_prompt_and_audio_from_messages,
)

logger = logging.getLogger(__name__)


class AnalyzeAudioRequestModel(BaseModel):
    prompt: str = Field(default=DEFAULT_AUDIO_PROMPT)
    audio_path: str = ""
    audio_url: str = ""
    audio_base64: str = ""
    audio_format: str = "wav"
    max_new_tokens: int = 96
    temperature: float = 0.0
    top_p: float = 1.0
    do_sample: bool = False

    @model_validator(mode="after")
    def validate_audio_input(self) -> AnalyzeAudioRequestModel:
        provided = [
            bool(str(self.audio_path).strip()),
            bool(str(self.audio_url).strip()),
            bool(str(self.audio_base64).strip()),
        ]
        if sum(provided) != 1:
            raise ValueError(
                "exactly one of audio_path, audio_url, audio_base64 is required"
            )
        return self

    def to_engine_request(self) -> InferenceRequest:
        return InferenceRequest(
            prompt=self.prompt,
            audio_path=self.audio_path,
            audio_url=self.audio_url,
            audio_base64=self.audio_base64,
            audio_format=self.audio_format,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            do_sample=self.do_sample,
        )


class ChatCompletionRequestModel(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    max_tokens: int = 96
    temperature: float = 0.0
    top_p: float = 1.0
    stream: bool = False


def create_app() -> FastAPI:
    config = ServiceConfig.from_env()
    engine = Gemma4AudioEngine(config)
    app = FastAPI(
        title="Gemma 4 E2B Audio Service",
        version="0.1.0",
        summary="Local macOS FastAPI service for Gemma 4 E2B native audio analysis",
    )

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            **engine.inspect(),
        }

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": config.model_id,
                    "object": "model",
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/audio/analyze")
    async def analyze_audio(request: AnalyzeAudioRequestModel):
        try:
            result = await run_inference(engine, request.to_engine_request())
        except (ServiceConfigError, AudioInputError, ModelLoadError) as exc:
            logger.warning("Gemma4 audio analyze rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "text": result.text,
            "model": result.model,
            "device": result.device,
            "prompt": result.prompt,
            "duration_seconds": result.duration_seconds,
            "load_seconds": result.load_seconds,
            "inference_seconds": result.inference_seconds,
            "quantization": result.quantization,
        }

    @app.post("/v1/audio/analyze-file")
    async def analyze_audio_file(
        file: UploadFile = File(...),
        prompt: str = DEFAULT_AUDIO_PROMPT,
        max_new_tokens: int = 96,
        temperature: float = 0.0,
        top_p: float = 1.0,
        do_sample: bool = False,
    ):
        raw = await file.read()
        request = AnalyzeAudioRequestModel(
            prompt=prompt,
            audio_base64=base64.b64encode(raw).decode("utf-8"),
            audio_format=(file.filename or "wav").split(".")[-1].lower() or "wav",
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            do_sample=do_sample,
        )
        try:
            result = await run_inference(engine, request.to_engine_request())
        except (ServiceConfigError, AudioInputError, ModelLoadError) as exc:
            logger.warning("Gemma4 audio analyze-file rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "text": result.text,
            "model": result.model,
            "device": result.device,
            "prompt": result.prompt,
            "duration_seconds": result.duration_seconds,
            "load_seconds": result.load_seconds,
            "inference_seconds": result.inference_seconds,
            "quantization": result.quantization,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatCompletionRequestModel):
        if request.stream:
            raise HTTPException(status_code=400, detail="stream=true is not supported")
        parsed = extract_prompt_and_audio_from_messages(request.messages)
        prompt = parsed.prompt or config.default_prompt
        if not (parsed.audio_path or parsed.audio_url or parsed.audio_base64):
            raise HTTPException(
                status_code=400, detail="no audio block found in messages"
            )
        try:
            result = await run_inference(
                engine,
                InferenceRequest(
                    prompt=prompt,
                    audio_path=parsed.audio_path,
                    audio_url=parsed.audio_url,
                    audio_base64=parsed.audio_base64,
                    audio_format=parsed.audio_format,
                    max_new_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    do_sample=request.temperature > 0.0,
                ),
            )
        except (ServiceConfigError, AudioInputError, ModelLoadError) as exc:
            logger.warning("Gemma4 audio chat rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        created = int(time.time())
        response_id = f"chatcmpl-{created}"
        return {
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": config.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result.text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "_gemma4_audio": {
                "device": result.device,
                "duration_seconds": result.duration_seconds,
                "load_seconds": result.load_seconds,
                "inference_seconds": result.inference_seconds,
                "quantization": result.quantization,
            },
        }

    return app


async def run_inference(engine: Gemma4AudioEngine, request: InferenceRequest):
    import asyncio

    return await asyncio.to_thread(engine.analyze, request)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    runtime_config = ServiceConfig.from_env()
    uvicorn.run(
        "scripts.gemma4_audio_service.app:app",
        host=runtime_config.host,
        port=runtime_config.port,
        reload=False,
    )
