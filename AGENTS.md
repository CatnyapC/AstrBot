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

## Pre-commit setup

AstrBot uses [pre-commit](https://pre-commit.com/) hooks to automatically format and lint Python code before each commit. The hooks run `ruff check`, `ruff format`, and `pyupgrade` (see [`.pre-commit-config.yaml`](.pre-commit-config.yaml) for details).

To set it up:

```bash
pip install pre-commit
pre-commit install
```

After installation, the hooks will run automatically on `git commit`. You can also run them manually at any time:

```bash
ruff format .
ruff check .
```

> **Note:** If you use VSCode, install the `Ruff` extension for real-time formatting and linting in the editor.

## Dev environment tips

1. When modifying the WebUI, be sure to maintain componentization and clean code. Avoid duplicate code.
2. Do not add any report files such as xxx_SUMMARY.md.
3. After finishing, use `ruff format .` and `ruff check .` to format and check the code.
4. When committing, ensure to use conventional commits messages, such as `feat: add new agent for data analysis` or `fix: resolve bug in provider manager`.
5. Use English for all new comments.
6. For path handling, use `pathlib.Path` instead of string paths, and use `astrbot.core.utils.path_utils` to get the AstrBot data and temp directory.
7. Group attribution exists to map messages about others to their targets (not the sender); if it fails, we fall back to the sender to keep updates safe.
8. Auto-impression Phase1/Phase2 now build `known_user_ids` strictly from the current batch: speakers, `@`/`reply_to` targets, and alias_map-resolved tokens in the message text. We no longer use `get_recent_profiles_by_group()` to supply known users.

## Plugin Workspace Routing

When a change touches one of these plugin workspaces, read and follow that plugin's AGENTS.md before editing code or docs:

- Thread Router: `data/plugins/astrbot_plugin_thread_router/` -> `data/plugins/astrbot_plugin_thread_router/AGENTS.md`
- Auto Impression Card / AIC: `data/plugins/astrbot_plugin_auto_impression_card/` -> `data/plugins/astrbot_plugin_auto_impression_card/AGENTS.md`
- Thread Archive: `data/plugins/astrbot_plugin_thread_archive/` -> `data/plugins/astrbot_plugin_thread_archive/AGENTS.md`

For cross-plugin work, read every touched plugin's AGENTS.md and apply the stricter local rule where instructions differ. Root-level AstrBot instructions apply only after the relevant plugin instructions are loaded.

## Documentation Ownership

- For plugin changes under `data/plugins/<plugin_name>/`, documentation ownership lives in that plugin workspace. Read the plugin's `AGENTS.md` first, then use that plugin's `docs/` lookup flow and update or add docs there.
- Do not create or update root-level `docs/` for plugin work unless the change truly modifies AstrBot root/core behavior outside `data/plugins/`. This should be rare for current work.
- For root/core AstrBot changes, use the root agent-managed documentation folder: `docs/`.
- Root documentation lookup flow:
  1. Open `docs/README.md`.
  2. Pick the matching category/subcategory.
  3. Open that folder's `README.md`.
  4. Only then open the concrete docs needed for the current task.
- Do not maintain per-file doc inventory in `AGENTS.MD`.

## PR instructions

1. Title format: use conventional commit messages
2. Use English to write PR title and descriptions.

## Release versions

1. Replace current version name to specific version name.
2. Write changelog in `changelogs/`, you can refer to the full commit messages between the latest tag to the latest commit.
3. Make and push a commit into master branch with message format like: `chore: bump version to 4.25.0`
4. Create a tag and push the tag. For example: `git tag v4.25.0 && git push origin v4.25.0`