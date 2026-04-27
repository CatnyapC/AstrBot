import json
from pathlib import Path

from astrbot.core.config.default import CONFIG_METADATA_3
from astrbot.core.config.i18n_utils import ConfigMetadataI18n

LOCALES = ("zh-CN", "en-US", "ru-RU")


def _collect_i18n_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"description", "hint", "labels", "name"} and isinstance(
                child, str
            ):
                keys.add(child)
            else:
                keys.update(_collect_i18n_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_collect_i18n_keys(child))
    return keys


def _has_key(data: dict, key: str) -> bool:
    current = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def test_config_metadata_i18n_keys_exist_for_all_locales():
    metadata = ConfigMetadataI18n.convert_to_i18n_keys(CONFIG_METADATA_3)
    required_keys = _collect_i18n_keys(metadata)
    root = Path(__file__).resolve().parents[1]

    missing = []
    for locale in LOCALES:
        locale_path = (
            root
            / "dashboard"
            / "src"
            / "i18n"
            / "locales"
            / locale
            / "features"
            / "config-metadata.json"
        )
        locale_data = json.loads(locale_path.read_text(encoding="utf-8"))
        for key in sorted(required_keys):
            if not _has_key(locale_data, key):
                missing.append(f"{locale}: {key}")

    assert missing == []
