from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def build_payload(user_id: int, self_id: int, message: str) -> dict:
    now = int(time.time())
    return {
        "time": now,
        "self_id": self_id,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": now,
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": message}}],
        "raw_message": message,
        "font": 0,
        "sender": {
            "user_id": user_id,
            "nickname": "error-notifier-tester",
            "card": "",
            "sex": "unknown",
            "age": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a synthetic OneBot private message to trigger error_notifier test command."
    )
    parser.add_argument(
        "--webhook-url",
        required=True,
        help="AstrBot webhook URL, e.g. http://127.0.0.1:6185/api/platform/webhook/<uuid>",
    )
    parser.add_argument("--user-id", required=True, type=int, help="Sender QQ user id")
    parser.add_argument("--self-id", required=True, type=int, help="Bot QQ self id")
    parser.add_argument(
        "--message",
        default="/error_notifier_test",
        help="Command text to send (default: /error_notifier_test)",
    )
    args = parser.parse_args()

    payload = build_payload(args.user_id, args.self_id, args.message)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        args.webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            print(f"HTTP {resp.status}")
            print(text[:500])
    except urllib.error.HTTPError as exc:
        print(f"HTTPError {exc.code}: {exc.read().decode('utf-8', errors='ignore')}")
        return 1
    except Exception as exc:
        print(f"Request failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
