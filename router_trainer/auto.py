"""Automatic training: from Home Assistant to a compared model in one job.

``router-trainer auto`` runs the whole road the studio otherwise takes step by step:

1. the inputs from Home Assistant (Assist Router's export) and the router code of the version
   Home Assistant runs;
2. the test: Home Assistant's own (``model_test.yaml``) or a new one written for this home -
   the judge already dropped the cases it did not trust, so nothing waits for a review;
3. the snapshot of the home, the frozen test, the generated data and the dataset;
4. training of each model, export to the home Ollama and the comparison with the model Assist
   Router uses now (``baseline``);
5. a summary (``auto/<dataset>.json``): per model the router's accuracy and time against the
   base, and which model to use. Nothing changes in Home Assistant - the studio's
   "Use in Assist Router" does that after a confirmation.
"""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import json
from pathlib import Path
from typing import Any

from . import ha_inputs, pipeline, router_source
from .config import Workspace, load_settings, ollama_name
from .generate.common import stage

TEST_HA = "ha"
TEST_NEW = "new"
# what the summary judges: the router part (the topic) is what the small model takes over
JUDGED_PART = "router"
RESULT = "@@auto"


def folder(ws: Workspace) -> Path:
    return ws.root / "auto"


def summary_path(ws: Workspace, dataset: str) -> Path:
    return folder(ws) / f"{dataset}.json"


def score(value: Any) -> float | None:
    """A part's score as a number: 0.93, "27/28" or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if "/" in text:
        done, _, total = text.partition("/")
        try:
            return float(Fraction(int(done), int(total))) if int(total) else None
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def verdict(report: dict[str, Any]) -> dict[str, Any]:
    """One model's comparison (``compare.json``) judged on the router part."""
    part = (report.get("parts") or {}).get(JUDGED_PART) or {}
    trained, base = score(part.get("trained")), score(part.get("base"))
    trained_s, base_s = part.get("trained_s"), part.get("base_s")
    accurate = trained is not None and (base is None or trained >= base)
    faster = trained_s is not None and base_s is not None and trained_s < base_s
    return {
        "trained": part.get("trained"),
        "base": part.get("base"),
        "trained_s": trained_s,
        "base_s": base_s,
        "fixed": len(part.get("fixed") or []),
        "broken": len(part.get("broken") or []),
        "accurate": accurate,
        "faster": faster,
        "better": accurate and (faster or base_s is None),
    }


def summarize(ws: Workspace, dataset: str, models: list[str]) -> dict[str, Any]:
    """The summary of an automatic run from the runs' comparisons (written next to them)."""
    settings = load_settings(ws)
    entries = []
    for model in models:
        run = pipeline.run_name(dataset, model)
        compare = ws.run(run) / "compare.json"
        entry: dict[str, Any] = {
            "model": model,
            "run": run,
            "ollama": ollama_name(settings, model, run),
        }
        if compare.is_file():
            report = json.loads(compare.read_text(encoding="utf-8"))
            entry |= verdict(report) | {"base_model": report.get("base")}
        else:
            entry["missing"] = True  # stopped or failed before the comparison
        entries.append(entry)
    better = [e for e in entries if e.get("better")]
    best = max(
        better, key=lambda e: (score(e["trained"]) or 0, -(e["trained_s"] or 0)), default=None
    )
    out = {
        "dataset": dataset,
        "finished": datetime.now().isoformat(timespec="minutes"),
        "models": entries,
        "recommended": best["run"] if best else None,
    }
    path = summary_path(ws, dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def latest(ws: Workspace) -> dict[str, Any] | None:
    """The newest summary, for the studio."""
    files = sorted(folder(ws).glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def prepare_inputs(ws: Workspace) -> dict[str, Any]:
    """Inputs from Home Assistant and the router code of its version (cloned when missing)."""
    stage("fetch")
    summary = ha_inputs.fetch_all(ws)
    print(f"from Home Assistant: {json.dumps(summary, ensure_ascii=False)}", flush=True)
    settings = load_settings(ws)
    try:
        matches = router_source.state(
            ws.root, settings["router_repo_setting"], summary.get("version")
        )["matches"]
    except (FileNotFoundError, ValueError):
        matches = False  # no router code yet
    if summary.get("version") and not matches:
        stage("router code")
        router_source.fetch(ws.root, str(summary["version"]))
        print(f"router code v{summary['version']}", flush=True)
    return summary


def choose_test(ws: Workspace, test: str, dataset: str) -> str:
    """The active test: Home Assistant's own, or a new one written for this home."""
    from . import context
    from .testset import build as testset_build, store

    if test == TEST_HA:
        if not (ws.root / load_settings(ws)["inputs"]["tests"]).is_file():
            raise FileNotFoundError(
                "Home Assistant has no model_test.yaml - choose a new test instead"
            )
        store.set_active(ws, TEST_HA)
        return TEST_HA
    if test != TEST_NEW:
        raise ValueError(f"unknown test {test!r} (ha or new)")
    testset_build.build(context.make(ws), dataset)
    store.set_active(ws, dataset)
    return dataset


ROLES = ("router", "control", "answers")


def run(
    ws: Workspace,
    dataset: str,
    models: list[str],
    test: str = TEST_HA,
    upload: bool = True,
    roles: tuple[str, ...] = ROLES,
) -> int:
    """``roles`` - what the model will do: ``("router",)`` when it only chooses the topic (the
    answer model parses commands and answers) - no commands and answers are generated."""
    pipeline.check_name(dataset, "dataset")
    if not models:
        raise ValueError("choose at least one model")
    roles = tuple(r for r in ROLES if r in roles)
    if "router" not in roles:
        raise ValueError("the router role is always trained")
    prepare_inputs(ws)
    active = choose_test(ws, test, dataset)
    print(f"test: {active}", flush=True)
    steps = [s for s in pipeline.STEPS if s != "testgen" and (s not in ROLES or s in roles)]
    if not upload:
        steps = [s for s in steps if s != "evaluate"]  # the comparison runs in the home Ollama
    code = pipeline.run(ws, steps, dataset, models, upload=upload, roles=roles)
    stage("summary")
    summary = summarize(ws, dataset, models)
    for entry in summary["models"]:
        print(f"{RESULT} {json.dumps(entry, ensure_ascii=False)}", flush=True)
    recommended = summary["recommended"]
    print(f"recommended: {recommended or 'none - keep the current router model'}", flush=True)
    return code
