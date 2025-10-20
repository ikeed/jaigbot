from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any


@lru_cache
def _load_text(package: str, name: str) -> str:
    """Load a text file from a package path and cache it.

    Using importlib.resources allows reading data from source or packaged wheels
    without worrying about filesystem layout.
    """
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def render_text(template_text: str, **kwargs: Any) -> str:
    """Very small templating: Python str.format with explicit kwargs.

    This avoids introducing a templating dependency while giving us simple
    placeholder substitution, e.g., "Hello {name}".
    """
    return template_text.format(**kwargs)


def load_and_render(package: str, name: str, **kwargs: Any) -> str:
    """Helper to load a template by name and render it with kwargs."""
    tmpl = _load_text(package, name)
    return render_text(tmpl, **kwargs)
