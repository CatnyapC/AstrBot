from __future__ import annotations

import base64

import pytest

from scripts.gemma4_audio_service.engine import (
    AudioInputError,
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


def test_guess_suffix_from_format_prefers_explicit_format():
    assert guess_suffix_from_format("wav") == ".wav"
    assert guess_suffix_from_format(".flac") == ".flac"
