"""trainer.yaml edited from the panel, like the router's and the dashboard's editors.

A draft changes nothing until it is saved; saving checks the text (YAML, the known sections,
numbers where numbers belong), refuses a file changed elsewhere since it was opened (its hash),
keeps the previous text as trainer.yaml.bak and as one of the last HISTORY_LIMIT versions, which
can be opened again as a draft.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import shutil
from typing import Any
import uuid

import yaml

from .config import EXAMPLE, Workspace, deep_merge

STORE_FILE = "settings_editor.json"  # in the workspace: draft + history
HISTORY_LIMIT = 30
SECTIONS = {
    "home_assistant", "router_repo", "inputs", "ollama", "generate", "test", "holdout",
    "dataset", "models", "export", "evaluate", "slot_values", "topic_overrides",
    "intent_topics", "fallback_topic", "music", "shopping_items",
    "sources",  # the old Mac share setting, read by nothing now
}  # fmt: skip
# numbers checked on save (a typo here would only fail hours later, in the middle of a job)
NUMBERS = {
    ("dataset", "dev_fraction"): (0.0, 0.5),
    ("holdout", "word_similarity"): (0.0, 1.0),
    ("holdout", "char_similarity"): (0.0, 1.0),
    ("generate", "router", "noise"): (0.0, 1.0),
}
MODEL_NUMBERS = {
    "epochs": (0.01, 20),
    "learning_rate": (1e-7, 1e-2),
    "lora_r": (1, 256),
    "lora_alpha": (1, 512),
    "batch_size": (1, 64),
    "grad_accum": (1, 128),
    "max_seq_length": (256, 32768),
}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _store_path(ws: Workspace):
    return ws.root / STORE_FILE


def _load_store(ws: Workspace) -> dict[str, Any]:
    try:
        data = json.loads(_store_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"draft": data.get("draft"), "history": list(data.get("history") or [])}


def _save_store(ws: Workspace, data: dict[str, Any]) -> None:
    ws.root.mkdir(parents=True, exist_ok=True)
    _store_path(ws).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def file_text(ws: Workspace) -> str:
    path = ws.config_file
    return path.read_text(encoding="utf-8") if path.exists() else EXAMPLE.read_text("utf-8")


def _number(value: Any, low: float, high: float, where: str) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return [f"{where}: a number"]
    if not low <= value <= high:
        return [f"{where}: between {low:g} and {high:g}"]
    return []


def check(text: str) -> dict[str, Any]:
    """{ok, error, warnings} - errors stop saving, warnings do not."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as err:
        return {"ok": False, "error": f"YAML: {err}", "warnings": []}
    if not isinstance(data, dict):
        return {"ok": False, "error": "trainer.yaml must be a map of sections", "warnings": []}
    merged = deep_merge(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")), data)
    errors: list[str] = []
    for path, (low, high) in NUMBERS.items():
        value: Any = merged
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None:
            errors += _number(value, low, high, ".".join(path))
    models = merged.get("models")
    if not isinstance(models, dict) or not models:
        errors.append("models: at least one model")
    else:
        for name, spec in models.items():
            for key, (low, high) in MODEL_NUMBERS.items():
                if isinstance(spec, dict) and key in spec:
                    errors += _number(spec[key], low, high, f"models.{name}.{key}")
    unknown = sorted(set(data) - SECTIONS)
    warnings = [f"unknown section: {key}" for key in unknown]
    return {"ok": not errors, "error": "; ".join(errors) or None, "warnings": warnings}


class Conflict(RuntimeError):
    """trainer.yaml changed elsewhere since the draft was begun (the studio answers 409)."""


def load(ws: Workspace) -> dict[str, Any]:
    """The file as it is (or the example when there is none yet), its check and the draft."""
    text = file_text(ws)
    current = text_hash(text)
    draft = _load_store(ws)["draft"]
    if draft:
        draft = {**draft, "outdated": draft.get("base") != current}
    return {
        "text": text,
        "hash": current,
        "exists": ws.config_file.exists(),
        "path": str(ws.config_file),
        "check": check(text),
        "draft": draft,
        # what applies where trainer.yaml says nothing (the forms show it as the placeholder)
        "defaults": yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")),
    }


def versions(ws: Workspace) -> list[dict[str, Any]]:
    """The saved versions, newest first: when, who, the note (the text with history_get)."""
    return [
        {k: h.get(k) for k in ("id", "time", "user", "note")} for h in _load_store(ws)["history"]
    ]


def save_draft(ws: Workspace, text: str, base: str) -> dict[str, Any]:
    store = _load_store(ws)
    store["draft"] = {"text": text, "base": base, "changed": _now()}
    _save_store(ws, store)
    return {"ok": True, "check": check(text)}


def discard(ws: Workspace) -> None:
    store = _load_store(ws)
    store["draft"] = None
    _save_store(ws, store)


def save(
    ws: Workspace, text: str, base: str, note: str = "", force: bool = False, user: str = ""
) -> dict[str, Any]:
    """Write trainer.yaml (the old text as .bak and in the history); the draft is cleared."""
    result = check(text)
    if not result["ok"]:
        raise ValueError(result["error"])
    current = file_text(ws)
    if not force and base != text_hash(current):
        raise Conflict("trainer.yaml was changed elsewhere since this draft was begun")
    path = ws.config_file
    ws.root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    store = _load_store(ws)
    if path.exists():
        store["history"].insert(
            0,
            {
                "id": uuid.uuid4().hex[:12],
                "time": _now(),
                "user": user,
                "note": note.strip(),
                "text": current,
            },
        )
        del store["history"][HISTORY_LIMIT:]
    store["draft"] = None
    path.write_text(text, encoding="utf-8")
    _save_store(ws, store)
    return {"ok": True, "hash": text_hash(text)}


def history_get(ws: Workspace, version: str) -> dict[str, Any]:
    for item in _load_store(ws)["history"]:
        if item["id"] == version:
            return item
    raise ValueError(f"no saved version {version!r}")


def restore(ws: Workspace, version: str) -> dict[str, Any]:
    """An old version back - as a draft, never straight into trainer.yaml."""
    item = history_get(ws, version)
    save_draft(ws, item["text"], text_hash(file_text(ws)))
    return {"text": item["text"]}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
