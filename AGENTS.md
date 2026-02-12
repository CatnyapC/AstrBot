## Setup commands

### Core

```
uv sync
uv run main.py
```

Exposed an API server on `http://localhost:6185` by default.

### Dashboard(WebUI)

```
cd dashboard
pnpm install # First time only. Use npm install -g pnpm if pnpm is not installed.
pnpm dev
```

Runs on `http://localhost:3000` by default.

## Dev environment tips

1. When modifying the WebUI, be sure to maintain componentization and clean code. Avoid duplicate code.
2. Do not add any report files such as xxx_SUMMARY.md.
3. After finishing, use `ruff format .` and `ruff check .` to format and check the code.
4. When committing, ensure to use conventional commits messages, such as `feat: add new agent for data analysis` or `fix: resolve bug in provider manager`.
5. Use English for all new comments.
6. For path handling, use `pathlib.Path` instead of string paths, and use `astrbot.core.utils.path_utils` to get the AstrBot data and temp directory.
7. Group attribution exists to map messages about others to their targets (not the sender); if it fails, we fall back to the sender to keep updates safe.
8. Auto-impression Phase1/Phase2 now build `known_user_ids` strictly from the current batch: speakers, `@`/`reply_to` targets, and alias_map-resolved tokens in the message text. We no longer use `get_recent_profiles_by_group()` to supply known users.

## PR instructions

1. Title format: use conventional commit messages
2. Use English to write PR title and descriptions.
