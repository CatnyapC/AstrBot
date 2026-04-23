# Gemma 4 Audio FastAPI Service

## Summary

This repo includes a standalone local FastAPI service for `Gemma 4 E2B` native audio analysis on macOS.

Path:

- `scripts/gemma4_audio_service/app.py`

## Runtime

- `FastAPI`
- `Transformers`
- `PyTorch MPS`
- `Pillow`
- `Torchvision`
- `Librosa`
- `SoundFile`
- optional `MetalConfig` quantization on Apple Silicon

## Endpoints

- `GET /healthz`
- `GET /v1/models`
- `POST /v1/audio/analyze`
- `POST /v1/audio/analyze-file`
- `POST /v1/chat/completions`

## Input Shapes

### Simple analyze

`POST /v1/audio/analyze`

```json
{
  "prompt": "请概括这段语音",
  "audio_path": "/absolute/path/to/audio.wav",
  "max_new_tokens": 192
}
```

Exactly one of these fields is required:

- `audio_path`
- `audio_url`
- `audio_base64`

### OpenAI-like chat

`POST /v1/chat/completions`

```json
{
  "model": "google/gemma-4-e2b-it",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "请概括这段语音"},
        {
          "type": "input_audio",
          "input_audio": {
            "data": "<base64>",
            "format": "wav"
          }
        }
      ]
    }
  ]
}
```

The compatibility endpoint also accepts:

- `{"type":"audio","audio":"/absolute/path.wav"}`
- `{"type":"audio","path":"/absolute/path.wav"}`
- `{"type":"audio_url","audio_url":{"url":"file:///absolute/path.wav"}}`

Local files are normalized to absolute `path` audio blocks before calling the Transformers chat template. In the pinned runtime, `file://` audio URLs can be handed to the feature extractor as text instead of a waveform.

## Install

Create a dedicated venv for the service, then install:

```bash
python3.12 -m venv .venv-gemma4-audio
source .venv-gemma4-audio/bin/activate
pip install -U pip
pip install -r scripts/gemma4_audio_service/requirements.txt
```

## Run

Recommended environment on macOS:

```bash
export PYTORCH_ENABLE_MPS_FALLBACK=1
export GEMMA4_AUDIO_MODEL_ID=google/gemma-4-e2b-it
export GEMMA4_AUDIO_USE_METAL_QUANTIZATION=false
export GEMMA4_AUDIO_QUANT_BITS=4
export GEMMA4_AUDIO_QUANT_GROUP_SIZE=64
uvicorn scripts.gemma4_audio_service.app:app --host 127.0.0.1 --port 4010
```

## Notes

- `MetalConfig` is attempted only on `mps`.
- On current Apple Silicon + `torch 2.11`, keeping Metal quantization off is the safer default.
- If `MetalConfig` is unavailable, the service falls back to standard `mps` loading.
- If `mps` loading fails with Metal buffer-size limits, the service can fall back to CPU when `GEMMA4_AUDIO_ALLOW_CPU_FALLBACK_ON_MPS_BUFFER_ERROR=true`.
- Generation logs include WAV signal stats (`rms_dbfs`, `peak_dbfs`) and a truncated raw completion. If every answer says the audio is unclear, check whether `rms_dbfs` is near silence before changing token limits.
- Very short WAV inputs are extended with trailing silence to `GEMMA4_AUDIO_MIN_SECONDS` seconds, default `4.0`, because Gemma 4 audio prompting is less reliable on about two-second clips. When this path is used, the service trims obvious repeated tails in the decoded completion.
- The service is intended for archive-side local media resolution, not for generic high-throughput serving.
- `astrbot_plugin_thread_archive` can point `record_caption_service_url` at this service.
