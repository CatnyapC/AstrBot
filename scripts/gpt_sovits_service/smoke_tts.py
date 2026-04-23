#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call_weights(base: str, endpoint: str, weights_path: str, timeout: float) -> None:
    url = f"{base.rstrip('/')}/{endpoint}?{urlencode({'weights_path': weights_path})}"
    with urlopen(url, timeout=timeout) as response:
        response.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:9880")
    parser.add_argument("--text", required=True)
    parser.add_argument("--text-lang", required=True)
    parser.add_argument("--ref-audio-path", required=True)
    parser.add_argument("--prompt-text", required=True)
    parser.add_argument("--prompt-lang", required=True)
    parser.add_argument("--out", default="/tmp/gpt_sovits_smoke.wav")
    parser.add_argument("--media-type", default="wav")
    parser.add_argument("--gpt-weights-path", default="")
    parser.add_argument("--sovits-weights-path", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    if args.gpt_weights_path:
        call_weights(base, "set_gpt_weights", args.gpt_weights_path, args.timeout)
    if args.sovits_weights_path:
        call_weights(base, "set_sovits_weights", args.sovits_weights_path, args.timeout)

    payload = {
        "text": args.text,
        "text_lang": args.text_lang,
        "ref_audio_path": args.ref_audio_path,
        "prompt_text": args.prompt_text,
        "prompt_lang": args.prompt_lang,
        "media_type": args.media_type,
        "streaming_mode": False,
    }
    request = Request(
        base + "/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=args.timeout) as response:
        audio = response.read()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    print(json.dumps({"out": str(out), "bytes": len(audio)}))


if __name__ == "__main__":
    main()
