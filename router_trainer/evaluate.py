"""Frozen test of a trained model and its base model in the home Ollama.

The router repository's ``tools/model_benchmark.py`` runs all five parts (router, control,
given data, HA data, Wikipedia) for both models, as in the model comparison of the docs. One
difference: the control test gets router.yaml's ``household`` - the integration's (and the
training data's) prompt - instead of the one in the test file. Both models get the same.

Afterwards ``compare.json`` lists, per part, both scores and the cases the training fixed or
broke; the log gets one ``@@result {...}`` line per part for the panel.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml

from .config import ollama_name
from .context import Context
from .export import run_params
from .generate.common import stage
from .teacher import http

RESULT = "@@result"
PARTS = ["router", "control", "answers", "real", "wiki_answers"]


def eval_cases(ctx: Context, run: Path) -> Path:
    tests = copy.deepcopy(ctx.tests())
    if "control" in tests:
        tests["control"]["household"] = ctx.config.household
    out = run / "eval_cases.yaml"
    out.write_text(yaml.safe_dump(tests, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def failures(entry: dict[str, Any], part: str) -> set[str]:
    """Names of the failed cases of one part (router: the question)."""
    if part not in entry:
        return set()
    if part == "router":
        return {error.split(" -> ")[0] for error in entry[part]["errors"]}
    return {d["case"] for d in entry[part]["details"] if d["problems"]}


def compare(results: dict[str, Any], trained: str, base: str) -> dict[str, Any]:
    out: dict[str, Any] = {"trained": trained, "base": base, "parts": {}}
    for part in PARTS:
        a, b = results.get(trained, {}), results.get(base, {})
        if part not in a:
            continue
        failed_a, failed_b = failures(a, part), failures(b, part)
        out["parts"][part] = {
            "total": a[part]["total"],
            "trained": a[part]["score"],
            "trained_s": round(a[part]["avg_s"], 2),
            "base": b.get(part, {}).get("score"),
            "base_s": round(b[part]["avg_s"], 2) if part in b else None,
            "fixed": sorted(failed_b - failed_a) if part in b else [],
            "broken": sorted(failed_a - failed_b) if part in b else [],
        }
    return out


def evaluate(ctx: Context, run_name: str, with_base: bool = True) -> dict[str, Any]:
    run = ctx.ws.run(run_name)
    params = run_params(run)
    trained = ollama_name(ctx.settings, params["model_key"], run_name)
    base = ctx.settings["models"][params["model_key"]]["baseline"]
    jetson = ctx.settings["ollama"]["jetson"].rstrip("/")
    for model in ctx.settings["evaluate"]["unload_first"] or []:
        print(f".. unloading {model} in the home Ollama", flush=True)
        http(jetson, "/api/generate", {"model": model, "keep_alive": 0}, timeout=120)
    models = [trained, base] if with_base else [trained]
    out = run / "eval.json"
    stage("test")
    command = [
        sys.executable,
        str(ctx.integ.repo / "tools" / "model_benchmark.py"),
        "--ollama",
        jetson,
        "--router-config",
        str(ctx.input("router")),
        "--cases",
        str(eval_cases(ctx, run)),
        "--data",
        str(ctx.test_data()),
        "--router",
        *models,
        "--answer",
        *models,
        # a missing base model is downloaded for the test and removed afterwards; models that
        # were there before (the trained one, HA's) stay
        "--pull",
        "--delete-after",
        "--resume",
        "--out",
        str(out),
    ]
    subprocess.run(command, check=True)
    results = json.loads(out.read_text(encoding="utf-8"))
    report = compare(results, trained, base)
    (run / "compare.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for part, data in report["parts"].items():
        line = {
            "part": part,
            **{k: v for k, v in data.items() if k not in ("fixed", "broken")},
            "fixed": len(data["fixed"]),
            "broken": len(data["broken"]),
        }
        print(f"{RESULT} {json.dumps(line, ensure_ascii=False)}", flush=True)
    return report
