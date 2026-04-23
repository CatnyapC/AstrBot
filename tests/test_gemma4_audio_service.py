from __future__ import annotations

import base64
import wave
from pathlib import Path

import pytest

from scripts.gemma4_audio_service.engine import (
    AudioInputError,
    Gemma4AudioEngine,
    ResolvedAudioInput,
    ServiceConfig,
    _extend_short_wav_input,
    _normalize_local_audio_path,
    _read_wav_duration_seconds,
    _trim_repeated_completion_tail,
    decode_base64_audio,
    extract_prompt_and_audio_from_messages,
    guess_suffix_from_format,
)


def test_decode_base64_audio_accepts_data_url():
    raw = b"fake-wav"
    encoded = "data:audio/wav;base64," + base64.b64encode(raw).decode("utf-8")

    assert decode_base64_audio(encoded) == raw


def test_decode_base64_audio_rejects_invalid_text():
    with pytest.raises(AudioInputError):
        decode_base64_audio("%%%")


def test_extract_prompt_and_audio_from_messages_supports_input_audio():
    parsed = extract_prompt_and_audio_from_messages(
        [
            {
                "role": "system",
                "content": [{"type": "text", "text": "系统规则"}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请分析这段音频"},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(b"abc").decode("utf-8"),
                            "format": "wav",
                        },
                    },
                ],
            },
        ]
    )

    assert parsed.prompt == "系统规则\n\n请分析这段音频"
    assert parsed.audio_base64 == base64.b64encode(b"abc").decode("utf-8")
    assert parsed.audio_format == "wav"


def test_extract_prompt_and_audio_from_messages_supports_audio_path():
    parsed = extract_prompt_and_audio_from_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": "/tmp/demo.wav"},
                    {"type": "text", "text": "总结内容"},
                ],
            }
        ]
    )

    assert parsed.audio_path == "/tmp/demo.wav"
    assert parsed.prompt == "总结内容"


def test_extract_prompt_and_audio_from_messages_supports_audio_path_key(tmp_path):
    audio_path = tmp_path / "demo.wav"
    audio_path.write_bytes(b"wav")

    parsed = extract_prompt_and_audio_from_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "总结内容"},
                    {"type": "audio", "path": str(audio_path)},
                ],
            }
        ]
    )

    assert parsed.audio_path == str(audio_path)
    assert parsed.prompt == "总结内容"


def test_normalize_local_audio_path_supports_file_uri(tmp_path):
    audio_path = tmp_path / "demo.wav"
    audio_path.write_bytes(b"wav")

    assert _normalize_local_audio_path(audio_path.as_uri()) == str(audio_path)


def test_build_messages_puts_text_before_audio(tmp_path):
    audio_path = tmp_path / "demo.wav"
    audio_path.write_bytes(b"wav")
    engine = Gemma4AudioEngine(ServiceConfig())

    messages = engine._build_messages(prompt="请总结", audio_path=str(audio_path))

    assert messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请总结"},
                {"type": "audio", "path": str(audio_path.resolve())},
            ],
        }
    ]


def test_extend_short_wav_input_pads_silence_to_min_seconds(tmp_path):
    audio_path = tmp_path / "short.wav"
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x01\x00" * 16000 * 2)

    extended = _extend_short_wav_input(
        ResolvedAudioInput(path=str(audio_path), duration_seconds=2.0),
        min_seconds=4.0,
        temp_dir=str(tmp_path),
    )

    try:
        assert extended.path != str(audio_path)
        assert _read_wav_duration_seconds(extended.path) == pytest.approx(4.0)
        with wave.open(extended.path, "rb") as wav_file:
            raw = wav_file.readframes(wav_file.getnframes())
        assert raw.endswith(b"\x00\x00" * 16)
        assert extended.extended_from_seconds == pytest.approx(2.0)
    finally:
        Path(extended.cleanup_path).unlink(missing_ok=True)


def test_trim_repeated_completion_tail_after_extension():
    text = "转写：狐米，你现在怎么样呀呀呀呀呀呀呀呀呀呀呀呀"

    assert _trim_repeated_completion_tail(text) == "转写：狐米，你现在怎么样呀…"


def test_guess_suffix_from_format_prefers_explicit_format():
    assert guess_suffix_from_format("wav") == ".wav"
    assert guess_suffix_from_format(".flac") == ".flac"
