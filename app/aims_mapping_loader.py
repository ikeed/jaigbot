from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from docs.aims import aims_mapping


@functools.lru_cache(maxsize=1)
def load_mapping(path: str | None = None) -> dict[str, Any]:
    """Load the operational AIMS mapping from an override or bundled path."""
    mapping_path = Path(path) if path else aims_mapping
    with mapping_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}
