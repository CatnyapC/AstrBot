# GPT-SoVITS TTS

AstrBot can use GPT-SoVITS through the existing text-to-speech pipeline. The LLM still returns text first. `ResultDecorateStage` then converts final `Plain` reply components into `Record` components when the master TTS switch and the current session TTS switch are both enabled.

## Provider

Use the built-in provider:

- Name: `GSV TTS(Local)`
- ID: `gsv_tts`
- Type: `gsv_tts_selfhost`

The provider targets the GPT-SoVITS `api_v2.py` sidecar:

- `POST /tts`
- `GET /set_gpt_weights`
- `GET /set_sovits_weights`

`/tts` is called with JSON. Config values keep their original types, so file paths, prompt text, language codes, booleans, and numeric sampling parameters are not lowercased or stringified.

## Local Sidecar Setup

Helper files:

- `scripts/gpt_sovits_service/setup.sh`
- `scripts/gpt_sovits_service/download_assets.sh`
- `scripts/gpt_sovits_service/run_api_v2.sh`
- `scripts/gpt_sovits_service/healthcheck.py`
- `scripts/gpt_sovits_service/smoke_tts.py`

Install into ignored local paths:

```bash
GPT_SOVITS_INSTALL_MODE=venv scripts/gpt_sovits_service/setup.sh
scripts/gpt_sovits_service/download_assets.sh
```

Defaults:

- upstream checkout: `.local-services/GPT-SoVITS`
- venv: `.venv-gpt-sovits`
- sidecar URL: `http://127.0.0.1:9880`

Run:

```bash
scripts/gpt_sovits_service/run_api_v2.sh
```

Check:

```bash
python3 scripts/gpt_sovits_service/healthcheck.py --base http://127.0.0.1:9880
```

Synthesis smoke test:

```bash
python3 scripts/gpt_sovits_service/smoke_tts.py \
  --text "测试语音合成" \
  --text-lang zh \
  --ref-audio-path /absolute/path/to/ref.wav \
  --prompt-text "reference transcript" \
  --prompt-lang zh \
  --out /tmp/gpt_sovits_smoke.wav
```

## Required Config

Enable the TTS provider globally:

```json
{
  "provider_tts_settings": {
    "enable": true,
    "provider_id": "gsv_tts",
    "dual_output": false
  }
}
```

Configure the provider with an absolute reference audio path and exact prompt text:

```json
{
  "api_base": "http://127.0.0.1:9880",
  "gpt_weights_path": "/absolute/path/to/model.ckpt",
  "sovits_weights_path": "/absolute/path/to/model.pth",
  "gsv_default_parms": {
    "gsv_ref_audio_path": "/absolute/path/to/ref.wav",
    "gsv_prompt_text": "exact reference transcript",
    "gsv_prompt_lang": "zh",
    "gsv_text_lang": "zh",
    "gsv_media_type": "wav"
  }
}
```

The provider validates these fields before synthesis:

- `ref_audio_path`
- `prompt_text`
- `prompt_lang`
- `text_lang`

`aux_ref_audio_paths` may be configured as a JSON list, a normal list, or a newline, semicolon, or comma-separated string. Empty optional values are omitted from the request.

Generated audio is written under AstrBot temp storage in `gsv_tts/`. The file suffix comes from `media_type`, defaulting to `wav`.

## Runtime

Enable TTS per session with `/tts`. Set `dual_output=true` for voice plus text, or `false` for voice-only replies.

Native GPT-SoVITS streaming is disabled for this provider version. Existing simulated sentence TTS remains the live-mode path.

## Thread Router

Thread router logic does not synthesize audio. It still owns incoming group routing: case gate, catchup, dispatch queue, prompt rewrite, and LLM request dispatch.

TTS happens after the router reply is generated, during core result decoration. Voice-only replies remain compatible with router dispatch completion because router `after_message_sent` treats non-`Plain` components such as `Record` as sendable.

For slow local synthesis, set `reply_dispatch_provider_call_timeout_sec` high enough to cover LLM latency, GPT-SoVITS synthesis, and platform upload time.
