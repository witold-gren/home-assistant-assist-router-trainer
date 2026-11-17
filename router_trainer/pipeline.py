"""Steps in order, as one job: data -> dataset -> training -> export -> test.

    router-trainer pipeline --steps router control answers build --dataset oct27
    router-trainer pipeline --steps train export evaluate --dataset oct27 --models e4b e2b

A run (one trained model) is ``workspace/runs/<dataset>-<model>`` unless named otherwise; its
``params.json`` keeps the model settings and the dataset it was trained on.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from . import evaluate as evaluate_module, export as export_module, holdout
from .config import Workspace, deep_merge, load_settings, model_settings
from .generate.common import stage
from .teacher import Teacher, local_url

DATA_STEPS = ("testgen", "snapshot", "freeze", "router", "control", "answers", "build")
MODEL_STEPS = ("train", "export", "evaluate")
STEPS = DATA_STEPS + MODEL_STEPS
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")


def check_name(name: str, what: str) -> str:
    if not NAME.match(name):
        raise ValueError(f"{what} {name!r}: lower-case letters, digits, . _ - (up to 41 chars)")
    return name


def run_name(dataset: str, model: str) -> str:
    return f"{dataset}-{model}"


def prepare_run(
    ws: Workspace, dataset: str, model: str, name: str, overrides: dict[str, Any] | None = None
) -> Path:
    """Write runs/<name>/params.json (kept when the run exists: Resume uses the same params)."""
    settings = load_settings(ws)
    folder = ws.run(check_name(name, "run"))
    params_file = folder / "params.json"
    if params_file.exists() and not overrides:
        return folder
    dataset_folder = ws.dataset(dataset)
    if not (dataset_folder / "train.jsonl").exists():
        raise FileNotFoundError(f"dataset {dataset} missing - build it first")
    params = {
        "model_key": model,
        "model": deep_merge(model_settings(settings, model), overrides or {}),
        "dataset": str(dataset_folder),
        "seed": settings["generate"]["seed"],
        "created": datetime.now().isoformat(timespec="minutes"),
    }
    folder.mkdir(parents=True, exist_ok=True)
    params_file.write_text(json.dumps(params, indent=1), encoding="utf-8")
    return folder


def free_gpu(settings: dict[str, Any]) -> None:
    """Unload the teacher from the trainer's Ollama (it takes most of the card)."""
    with contextlib.suppress(OSError):
        Teacher(local_url(settings), settings["ollama"]["teacher"]).unload()


def train(ws: Workspace, name: str, resume: bool = False) -> int:
    settings = load_settings(ws)
    folder = ws.run(name)
    free_gpu(settings)
    python = export_module.TRAIN_PYTHON
    if not python.exists():
        raise FileNotFoundError(f"{python} missing - run scripts/setup.sh on the GPU machine")
    stage(f"train {name}")
    command = [str(python), "-m", "router_trainer.train", "--run", str(folder)]
    if resume:
        command.append("--resume")
    return subprocess.run(command, cwd=export_module.REPO, check=False).returncode


def run(
    ws: Workspace,
    steps: list[str],
    dataset: str,
    models: list[str],
    resume: bool = False,
    upload: bool = True,
    with_base: bool = True,
    overrides: dict[str, Any] | None = None,
) -> int:
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        raise ValueError(f"unknown steps: {', '.join(unknown)} (known: {', '.join(STEPS)})")
    check_name(dataset, "dataset")
    ctx = None
    if any(s in steps for s in (*DATA_STEPS, "export", "evaluate")):
        from . import context

        ctx = context.make(ws)
    for step in [s for s in STEPS if s in steps and s in DATA_STEPS]:
        if step == "testgen":
            from .testset import build as testset_build

            testset_build.build(ctx, dataset)
        elif step == "snapshot":
            from .generate import snapshot

            snapshot.take(ctx)
        elif step == "freeze":
            stage("freeze")
            frozen = holdout.freeze(ctx.tests(), ctx.settings, ws.holdout)
            print(f"frozen test: {len(frozen.sentences)} sentences", flush=True)
        elif step == "router":
            from .generate import router

            router.generate(ctx)
        elif step == "control":
            from .generate import control

            control.generate(ctx)
        elif step == "answers":
            from .generate import answers

            answers.generate(ctx)
        elif step == "build":
            from .generate import build

            build.build(ctx, dataset)
    if not any(s in steps for s in MODEL_STEPS):
        return 0
    if ctx is not None and "train" in steps:
        free_gpu(ctx.settings)
    for model in models:
        name = run_name(dataset, model)
        if "train" in steps:
            prepare_run(ws, dataset, model, name, overrides)
            code = train(ws, name, resume)
            if code != 0:
                return code  # stopped (130) or failed: the next models wait
        if "export" in steps:
            export_module.export(ctx, name, upload=upload)
        if "evaluate" in steps:
            evaluate_module.evaluate(ctx, name, with_base=with_base)
    return 0
