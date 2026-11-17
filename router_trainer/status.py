"""State of a workspace for the panel, as one JSON (``router-trainer status``).

Light on purpose: it imports neither Home Assistant nor the integration and only reads small
files, because the panel asks for it every few seconds (over SSH in remote mode).
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .config import Workspace, load_settings
from .jobs import JobManager, read_log

GPU_QUERY = [
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
]


def parse_gpu(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return None

    def number(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None

    return {
        "name": parts[0],
        "utilization": number(parts[1]),
        "memory_used": number(parts[2]),
        "memory_total": number(parts[3]),
        "temperature": number(parts[4]),
        "power": number(parts[5]),
    }


def gpu() -> dict[str, Any] | None:
    try:
        result = subprocess.run(GPU_QUERY, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return parse_gpu(result.stdout.strip().splitlines()[0])


def _json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def datasets(ws: Workspace) -> list[dict[str, Any]]:
    out = []
    for folder in sorted(ws.datasets.glob("*")) if ws.datasets.exists() else []:
        card = _json(folder / "card.json")
        if card:
            out.append(
                {
                    k: card.get(k)
                    for k in (
                        "name",
                        "created",
                        "train",
                        "dev",
                        "roles",
                        "sources",
                        "topics",
                        "fingerprint",
                        "holdout_rejected",
                        "holdout_samples",
                    )
                }
            )
    return out


def _resume(checkpoint: Path) -> dict[str, Any] | None:
    state = _json(checkpoint / "trainer_state.json")
    if not state:
        return None
    return {"step": state.get("global_step"), "max_steps": state.get("max_steps"),
            "epoch": state.get("epoch")}  # fmt: skip


def runs(ws: Workspace) -> list[dict[str, Any]]:
    out = []
    for folder in sorted(ws.runs.glob("*")) if ws.runs.exists() else []:
        params = _json(folder / "params.json")
        if not params:
            continue
        checkpoints = sorted(
            folder.glob("checkpoints/checkpoint-*"), key=lambda c: int(c.name.rsplit("-", 1)[-1])
        )
        out.append(
            {
                "name": folder.name,
                "model": params.get("model_key"),
                "dataset": Path(params.get("dataset", "")).name,
                "created": params.get("created"),
                "settings": params.get("model"),
                "checkpoint": checkpoints[-1].name if checkpoints else None,
                # Resume continues from here: the step reached and the planned total
                "resume": _resume(checkpoints[-1]) if checkpoints else None,
                "trained": (folder / "merged").exists(),
                "train_info": _json(folder / "train_info.json"),
                "export": _json(folder / "export.json"),
                "compare": _json(folder / "compare.json"),
            }
        )
    return out


def test_listing(ws: Workspace, settings: dict[str, Any]) -> dict[str, Any]:
    from .testset import store

    try:
        return store.listing(ws, settings)
    except Exception as err:  # a broken test file must not break the panel
        return {"active": store.active(ws), "tests": [], "error": str(err)}


def status(ws: Workspace, offset: int = 0) -> dict[str, Any]:
    settings = load_settings(ws)
    job = JobManager(ws.root).status()
    log = read_log(Path(job.log), offset) if job else b""
    snapshot = _json(ws.snapshot)
    frozen = _json(ws.holdout)
    inputs = {name: _mtime(ws.path(relative)) for name, relative in settings["inputs"].items()}
    return {
        "workspace": str(ws.root),
        "job": job.as_dict() if job else None,
        "log": log.decode("utf-8", errors="replace"),
        "log_offset": offset + len(log),
        "gpu": gpu(),
        "inputs": inputs,
        "snapshot": {
            "taken": snapshot.get("taken"),
            "targets": len(snapshot["home"]["targets"]),
            "fingerprint": snapshot.get("fingerprint"),
        }
        if snapshot
        else None,
        "holdout": {"sentences": len(frozen["sentences"]), "file": str(ws.holdout)}
        if frozen
        else None,
        "generated": {
            role: _lines(ws.generated / f"{role}.jsonl")
            for role in ("router", "control", "answers")
        },
        "datasets": datasets(ws),
        "runs": runs(ws),
        "models": list(settings["models"]),
        "model_settings": settings["models"],
        "jetson": settings["ollama"]["jetson"],
        "tests": test_listing(ws, settings),
    }
