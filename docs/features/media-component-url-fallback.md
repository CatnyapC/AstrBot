# Media Component URL Fallback

## Summary

Some OneBot/NapCat inbound media segments carry a hash-like filename in `file` and the real download address in `url`.

AstrBot now resolves inbound `Record` and `Video` media from `url` first, then falls back to `file`.

## Why

Without this fallback, `convert_to_file_path()` treated values like `ca2a2de85023dd03e2ad18fcbc588471.mp4` or `e2c6e2ea8d298f0aff705e08e1e2535b.amr` as local paths.

That made thread-archive media persistence fail before thread-router could consume archived `media_paths`.

## Scope

- `Record.convert_to_file_path()`
- `Record.convert_to_base64()`
- `Video.convert_to_file_path()`
- `Video` now preserves inbound `url`
