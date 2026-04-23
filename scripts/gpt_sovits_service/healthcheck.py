#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:9880")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    url = args.base.rstrip("/") + "/control"
    try:
        with urlopen(url, timeout=args.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(json.dumps({"status": "ok", "code": response.status, "body": body}))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "command" in body:
            print(json.dumps({"status": "ok", "code": exc.code, "body": body}))
            return
        raise


if __name__ == "__main__":
    main()
