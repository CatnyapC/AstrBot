# WebUI Config Metadata I18n Missing Keys

## Symptom

WebUI config labels or hints render as:

```text
[MISSING: features.config-metadata.ai_group...description]
[MISSING: features.config-metadata.ai_group...hint]
```

This often appears after merging upstream changes that add new fields to `CONFIG_METADATA_3`.

## Cause

Core config metadata is converted to i18n keys by `ConfigMetadataI18n.convert_to_i18n_keys()`.

Every `description`, `hint`, `labels`, and `name` generated from `astrbot/core/config/default.py` must exist in:

- `dashboard/src/i18n/locales/zh-CN/features/config-metadata.json`
- `dashboard/src/i18n/locales/en-US/features/config-metadata.json`
- `dashboard/src/i18n/locales/ru-RU/features/config-metadata.json`

Also note: `uv run main.py` serves `data/dist` first if it exists. Editing `dashboard/src` does not affect the running WebUI until the dashboard is rebuilt and copied into `data/dist`.

## Check

Run the regression test:

```bash
uv run pytest tests/test_config_metadata_i18n.py
```

Or inspect which WebUI bundle is active:

```bash
cat data/dist/assets/version 2>/dev/null || true
rg -n "missing_key_or_expected_text" data/dist/assets/*.js
```

## Fix

1. Add missing translations to all locale files under `dashboard/src/i18n/locales/*/features/config-metadata.json`.
2. Run:

```bash
uv run ruff check .
uv run pytest tests/test_config_metadata_i18n.py
```

3. Rebuild and replace the served dashboard:

```bash
cd dashboard
corepack pnpm install
corepack pnpm build
cd ..
rsync -a --delete dashboard/dist/ data/dist/
```

4. Hard refresh the browser (`Cmd+Shift+R` on macOS). If stale content remains, clear site cache.
