"""A quick check of the whole road on the GPU machine (``router-trainer smoke``, ~15-25 min).

A separate workspace (workspace-smoke next to the real one) gets copies of the inputs, the HA
connection and trainer.yaml with very small numbers; then every step runs once: a small
generated test (writer + judge), snapshot, frozen test, router / control / answers data with
the teacher, dataset, a short E2B training, GGUF, upload to the home Ollama, test against the
base model. At the end the smoke model is removed from the home Ollama (``--keep`` leaves it).
Nothing of the real workspace changes.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import yaml

from . import pipeline
from .config import Workspace, init_workspace, load_settings, ollama_name
from .teacher import http

SMALL = {
    "seed": 7,
    "router": {
        "paraphrases_per_topic": 3,
        "per_template": 2,
        "native_intents": 80,
        "knowledge": 10,
        "gibberish": 10,
        "log_questions": False,
        "max_per_topic": 30,
        "min_per_topic": 5,
        "noise": 0.3,
    },
    "control": {"labels": 6, "sentences_per_label": 2},
    "answers": {"given": 6, "live_per_topic": 1, "wikipedia": 3},
}
# a small generated test (the writer and the judge are checked too)
SMALL_TEST = {
    "seed": 7,
    "router_per_topic": 1,
    "control": 4,
    "answers": 3,
    "real_per_topic": 1,
    "real_max": 3,
    "wikipedia": 2,
}
DATASET = "smoke"


def prepare(ws: Workspace) -> Workspace:
    """workspace-smoke from the real workspace (inputs, HA connection, settings)."""
    smoke = Workspace(ws.root.parent / f"{ws.root.name}-smoke")
    if smoke.root.exists():
        shutil.rmtree(smoke.root)
    init_workspace(smoke.root)
    for name in ("inputs",):
        if (ws.root / name).exists():
            shutil.copytree(ws.root / name, smoke.root / name)
    for name in ("home_assistant.json", "ha_token"):
        if (ws.root / name).exists():
            shutil.copy2(ws.root / name, smoke.root / name)
    own = (
        yaml.safe_load(ws.config_file.read_text(encoding="utf-8"))
        if ws.config_file.exists()
        else {}
    )
    own = own or {}
    own["generate"] = SMALL
    own["test"] = SMALL_TEST
    smoke.config_file.write_text(
        yaml.safe_dump(own, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    # the teacher already downloaded for the real workspace (hard links: no extra space)
    models = ws.root / "ollama-models"
    if models.exists():
        shutil.copytree(models, smoke.root / "ollama-models", copy_function=_link)
    return smoke


def _link(source: str, target: str) -> None:
    try:
        Path(target).hardlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def run(ws: Workspace, model: str = "e2b", keep: bool = False) -> int:
    smoke = prepare(ws)
    print(f"==> smoke workspace {smoke.root}", flush=True)
    code = pipeline.run(
        smoke,
        [
            "testgen",
            "snapshot",
            "freeze",
            "router",
            "control",
            "answers",
            "build",
            "train",
            "export",
            "evaluate",
        ],
        DATASET,
        [model],
        overrides={"epochs": 0.5},
    )
    if code != 0:
        print(f"!! smoke test stopped with code {code} - see the log above", flush=True)
        return code
    run_name = pipeline.run_name(DATASET, model)
    report = json.loads((smoke.run(run_name) / "compare.json").read_text(encoding="utf-8"))
    print("\nsmoke test - trained / base (small generated test, a few training steps):")
    for part, data in report["parts"].items():
        print(f"  {part:13} {data['trained']}/{data['total']}  {data['base']}/{data['total']}")
    settings = load_settings(smoke)
    if not keep:
        name = ollama_name(settings, model, run_name)
        try:
            http(
                settings["ollama"]["jetson"],
                "/api/delete",
                {"model": name},
                timeout=60,
                method="DELETE",
            )
            print(f"removed {name} from the home Ollama", flush=True)
        except OSError as err:
            print(f"!! could not remove {name}: {err}", flush=True)
    print("== smoke test passed: data, training, export and test work", flush=True)
    return 0
