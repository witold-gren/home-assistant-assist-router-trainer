"""Language packs of the trainer: teacher prompts and vocabulary for made-up data.

The pack is chosen by the integration's language (``LANG.CODE`` of the Assist Router pack in
use), so data are generated in the language the integration speaks. Another language = a new
module here with the same names as ``pl.py``.
"""

from __future__ import annotations

from importlib import import_module
import pkgutil
from types import ModuleType


def available() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))


def get(code: str) -> ModuleType:
    if code not in available():
        raise ValueError(f"no trainer language pack {code!r} (available: {', '.join(available())})")
    return import_module(f"{__name__}.{code}")
