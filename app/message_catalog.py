from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_LOCALE = "en"
_LOCALE_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=8)
def _load_catalog(locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
    locale_name = locale or DEFAULT_LOCALE
    path = _LOCALE_DIR / f"{locale_name}.json"
    if not path.exists() and locale_name != DEFAULT_LOCALE:
        path = _LOCALE_DIR / f"{DEFAULT_LOCALE}.json"
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def catalog_value(key: str, *, locale: str = DEFAULT_LOCALE, default: Any = None) -> Any:
    current: Any = _load_catalog(locale)
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def message(key: str, *, locale: str = DEFAULT_LOCALE, default: str | None = None, **values: Any) -> str:
    template = catalog_value(key, locale=locale, default=default if default is not None else key)
    if not isinstance(template, str):
        return str(default if default is not None else key)
    if not values:
        return template
    try:
        return template.format(**values)
    except Exception:
        return template


def message_list(key: str, *, locale: str = DEFAULT_LOCALE) -> list[str]:
    value = catalog_value(key, locale=locale, default=[])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def message_map(key: str, *, locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
    value = catalog_value(key, locale=locale, default={})
    return dict(value) if isinstance(value, dict) else {}
