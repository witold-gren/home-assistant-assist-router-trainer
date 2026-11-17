"""Tests of a workspace: the active one, the generated ones and their review.

The active test is either ``ha`` (the test file copied from the HA share, ``inputs.tests``) or
a generated test in workspace/tests/<name>/. Cases rejected in the review are left out of the
active test everywhere: the frozen test, the evaluation, the smoke test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

from ..config import Workspace
from ..holdout import normalize

HA_TEST = "ha"
ACTIVE_FILE = "active_test.json"
TEST_FILE = "model_test.yaml"
DATA_FILE = "model_test_data.yaml"
REVIEW_FILE = "review.json"
CARD_FILE = "card.json"
SECTIONS = ("router", "control", "answers", "real", "wiki_answers")


def tests_dir(ws: Workspace) -> Path:
    return ws.root / "tests"


def test_dir(ws: Workspace, name: str) -> Path:
    return tests_dir(ws) / name


def active(ws: Workspace) -> str:
    try:
        return json.loads((ws.root / ACTIVE_FILE).read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError):
        return HA_TEST


def set_active(ws: Workspace, name: str) -> None:
    if name != HA_TEST and not (test_dir(ws, name) / TEST_FILE).exists():
        raise ValueError(f"no generated test {name!r}")
    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.root / ACTIVE_FILE).write_text(json.dumps({"name": name}) + "\n", encoding="utf-8")


def paths(ws: Workspace, settings: dict[str, Any], name: str | None = None) -> tuple[Path, Path]:
    """(test file, its snapshot) of a test (default: the active one)."""
    name = name or active(ws)
    if name == HA_TEST:
        return ws.path(settings["inputs"]["tests"]), ws.path(settings["inputs"]["test_data"])
    folder = test_dir(ws, name)
    return folder / TEST_FILE, folder / DATA_FILE


def case_id(section: str, case: Any) -> str:
    """A stable id of one case (router and control by the sentence, the rest by name)."""
    if section == "router":
        return f"router:{normalize(case[0])}"
    if section == "control":
        return f"control:{normalize(case['text'])}"
    return f"{section}:{case['name']}"


def section_cases(tests: dict[str, Any], section: str) -> list[Any]:
    value = tests.get(section)
    if section == "router":
        return list(value or [])
    return list((value or {}).get("cases") or [])


def review_file(ws: Workspace, name: str) -> Path:
    if name == HA_TEST:
        return ws.root / f"{HA_TEST}-{REVIEW_FILE}"
    return test_dir(ws, name) / REVIEW_FILE


def rejected(ws: Workspace, name: str) -> set[str]:
    file = review_file(ws, name)
    try:
        return set(json.loads(file.read_text(encoding="utf-8")).get("rejected", []))
    except (OSError, ValueError):
        return set()


def set_rejected(ws: Workspace, name: str, case: str, value: bool) -> set[str]:
    ids = rejected(ws, name)
    if value:
        ids.add(case)
    else:
        ids.discard(case)
    file = review_file(ws, name)
    file.parent.mkdir(parents=True, exist_ok=True)
    data = {"rejected": sorted(ids)}
    file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return ids


def without_rejected(tests: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    out = copy.deepcopy(tests)
    if not ids:
        return out
    for section in SECTIONS:
        if section not in out:
            continue
        kept = [c for c in section_cases(out, section) if case_id(section, c) not in ids]
        if section == "router":
            out[section] = kept
        else:
            out[section]["cases"] = kept
    return out


def load(ws: Workspace, settings: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    """A test without its rejected cases (default: the active test)."""
    name = name or active(ws)
    file, _ = paths(ws, settings, name)
    if not file.exists():
        raise FileNotFoundError(
            f"test {name!r} missing ({file}) - generate one or send the test file from HA"
        )
    tests = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return without_rejected(tests, rejected(ws, name))


def expectation(section: str, case: Any) -> str:
    """What a case expects, in a few words for the review list."""
    if section == "router":
        topics = case[1]
        return " / ".join(topics) if isinstance(topics, list) else str(topics)
    if section == "control":
        return ", ".join(f"{k}={v}" for k, v in case["expect"].items())
    must = ["|".join(m) if isinstance(m, list) else m for m in case.get("must", [])]
    out = "must: " + "; ".join(must)
    if case.get("never"):
        out += " · never: " + "; ".join(case["never"])
    return out


def review_list(ws: Workspace, settings: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """Every case of a test for the review: section, sentence, expectation, rejected."""
    file, _ = paths(ws, settings, name)
    tests = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    ids = rejected(ws, name)
    out = []
    for section in SECTIONS:
        for case in section_cases(tests, section):
            text = case[0] if section == "router" else case.get("text") or case.get("question")
            cid = case_id(section, case)
            out.append({"id": cid, "section": section, "text": text,
                        "expect": expectation(section, case), "rejected": cid in ids})  # fmt: skip
    return out


def listing(ws: Workspace, settings: dict[str, Any]) -> dict[str, Any]:
    """The tests the panel can choose from, with counts."""
    out = []
    ha_file, _ = paths(ws, settings, HA_TEST)
    candidates = (
        [(HA_TEST, ha_file)]
        + [
            (folder.name, folder / TEST_FILE)
            for folder in sorted(tests_dir(ws).glob("*"))
            if (folder / TEST_FILE).exists()
        ]
        if tests_dir(ws).exists()
        else [(HA_TEST, ha_file)]
    )
    for name, file in candidates:
        if not file.exists():
            continue
        try:
            tests = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        card = {}
        if name != HA_TEST:
            try:
                card = json.loads((file.parent / CARD_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                card = {}
        out.append({
            "name": name,
            "counts": {s: len(section_cases(tests, s)) for s in SECTIONS},
            "rejected": len(rejected(ws, name)),
            "created": card.get("created"),
            "dropped": card.get("dropped"),
        })  # fmt: skip
    return {"active": active(ws), "tests": out}
