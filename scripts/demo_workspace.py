"""A made-up workspace for the studio demo, its screenshots and the browser tests.

The example household of the router (Tomek, Ania, Ola, Kuba; no real home data): inputs, a test with a
review, a dataset, two runs with results and a training in progress with its log; a pretend GPU
(nvidia-smi) and a pretend Home Assistant for the machine's power. The numbers are illustrations.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

from router_trainer.config import Workspace, init_workspace

TRY_RESULT = {
    "text": "Zgaś lampkę przy kanapie",
    "models": {
        "assist-router-e4b-ft:demo-e4b": {
            "topic": "sterowanie",
            "router_s": 0.41,
            "control": {
                "intencja": "HassTurnOff",
                "domena": "light",
                "obszar": "Salon",
                "nazwa": "lampkę przy kanapie",
            },
            "device": "Lampa przy kanapie",
        },
        "gemma4:e4b": {
            "topic": "sterowanie",
            "router_s": 0.52,
            "control": {
                "intencja": "HassTurnOff",
                "domena": "light",
                "obszar": None,
                "nazwa": "lampkę",
            },
            "device": None,
        },
    },
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def demo_workspace(root: Path) -> Workspace:
    ws = init_workspace(root)
    write(ws.root / "ha_token", "demo\n")
    write(
        ws.ha_file,
        json.dumps(
            {
                "url": "http://homeassistant.local:8123",
                "token_file": "ha_token",
                "checked": {"name": "Dom", "version": "2026.10.4"},
                "power": {
                    "switch": "switch.maszyna_gpu",
                    "sensor": "sensor.gniazdko_komputer_moc",
                    "off_watts": 5.0,
                },
            }
        ),
    )
    for name in (
        "router.yaml",
        "model_test.yaml",
        "model_test_data.yaml",
        "unrecognized_commands.csv",
        "ha_config/automations.yaml",
    ):
        write(ws.root / "inputs" / name, "# demo\n")
    write(
        ws.snapshot,
        json.dumps(
            {"taken": "2026-10-27T20:05", "home": {"targets": [{}] * 214}, "fingerprint": "a1b2c3"}
        ),
    )
    write(
        ws.holdout,
        json.dumps({"sentences": ["x"] * 651, "word_similarity": 0.8, "char_similarity": 0.85}),
    )
    for role, count in (("router", 9420), ("control", 2870), ("answers", 1715)):
        write(ws.generated / f"{role}.jsonl", "{}\n" * count)
    samples = [
        {"role": "router", "text": "czy ola ma jutro basen", "test": "Czy Ola ma jutro basen?"},
        {"role": "router", "text": "Włącz swiatło w kuchni", "test": "Włącz światło w kuchni"},
        {"role": "control", "text": "Zgaś lampke w salonie", "test": "Zgaś lampkę w salonie"},
    ]
    write(
        ws.dataset("demo") / "card.json",
        json.dumps(
            {
                "name": "demo",
                "created": "2026-10-27T22:40",
                "train": 12890,
                "dev": 680,
                "roles": {"router": 8730, "control": 2860, "answers": 1980},
                "fingerprint": "a1b2c3",
                "holdout_rejected": 412,
                "holdout_samples": samples,
            },
            ensure_ascii=False,
        ),
    )
    write(ws.dataset("demo") / "train.jsonl", "")
    test = ws.root / "tests" / "test1"
    write(
        test / "model_test.yaml",
        "router:\n"
        + "".join(f"- [Pytanie {i}, kalendarz]\n" for i in range(336))
        + "control:\n  cases:\n"
        + "".join(
            f"  - {{text: Polecenie {i}, expect: {{intent: HassTurnOn}}}}\n" for i in range(150)
        )
        + "answers:\n  cases:\n"
        + "".join(f"  - {{name: a{i}, question: q, data: d, must: [x]}}\n" for i in range(35))
        + "real:\n  cases:\n"
        + "".join(f"  - {{name: r{i}, topic: t, question: q, must: [x]}}\n" for i in range(82))
        + "wiki_answers:\n  cases:\n"
        + "".join(f"  - {{name: w{i}, source: s, question: q, must: [x]}}\n" for i in range(15)),
    )
    write(
        test / "card.json",
        json.dumps({"created": "2026-10-27T21:10", "dropped": {"router": 41, "control": 63}}),
    )
    write(test / "review.json", json.dumps({"rejected": ["router:pytanie 3", "router:pytanie 7"]}))
    write(ws.root / "active_test.json", json.dumps({"name": "test1"}))
    compare_e4b = {
        "trained": "assist-router-e4b-ft:demo-e4b",
        "base": "gemma4:e4b",
        "parts": {
            "router": {
                "total": 379,
                "trained": 371,
                "trained_s": 0.58,
                "base": 359,
                "base_s": 0.54,
                "fixed": 15,
                "broken": 3,
            },
            "control": {
                "total": 155,
                "trained": 146,
                "trained_s": 2.31,
                "base": 139,
                "base_s": 2.43,
                "fixed": 11,
                "broken": 4,
            },
            "answers": {
                "total": 34,
                "trained": 34,
                "trained_s": 0.71,
                "base": 34,
                "base_s": 0.68,
                "fixed": 0,
                "broken": 0,
            },
            "real": {
                "total": 86,
                "trained": 77,
                "trained_s": 1.80,
                "base": 72,
                "base_s": 1.71,
                "fixed": 8,
                "broken": 3,
            },
            "wiki_answers": {
                "total": 15,
                "trained": 14,
                "trained_s": 3.52,
                "base": 14,
                "base_s": 3.64,
                "fixed": 1,
                "broken": 1,
            },
        },
    }
    for model, minutes, loss in (("e4b", 142.5, 0.412), ("e2b", 71.0, 0.468)):
        run = ws.run(f"demo-{model}")
        write(
            run / "params.json",
            json.dumps(
                {
                    "model_key": model,
                    "dataset": str(ws.dataset("demo")),
                    "created": "2026-10-27T23:00",
                    "model": {"epochs": 1},
                }
            ),
        )
        (run / "merged").mkdir(parents=True, exist_ok=True)
        write(run / "train_info.json", json.dumps({"minutes": minutes, "loss": loss}))
        write(run / "export.json", json.dumps({"name": f"assist-router-{model}-ft:demo-{model}"}))
        if model == "e4b":
            write(run / "compare.json", json.dumps(compare_e4b))
    # a running training: generation counters, then the loss curve
    lines = [
        "$ router-trainer pipeline --steps train export evaluate --dataset demo --models e4b e2b"
    ]
    for part, done, target, rejected in (
        ("paraphrase:kalendarz", 300, 300, 4),
        ("control", 2870, 4500, 1130),
        ("live", 1715, 1800, 85),
    ):
        role = (
            "router"
            if part.startswith("paraphrase")
            else ("control" if part == "control" else "answers")
        )
        lines.append(
            "@@progress "
            + json.dumps(
                {"role": role, "part": part, "done": done, "target": target, "rejected": rejected}
            )
        )
    lines += [
        "==> train demo-e2b",
        '@@info {"train": 12890, "dev": 680, "base": "unsloth/gemma-4-E2B-it"}',
    ]
    for step in range(10, 520, 10):
        loss = 0.38 + 1.9 * math.exp(-step / 70) + 0.03 * math.sin(step / 9)
        lines.append(
            "@@metric " + json.dumps({"step": step, "max_steps": 806, "loss": round(loss, 4)})
        )
        if step % 100 == 0:
            lines.append(
                "@@metric "
                + json.dumps(
                    {
                        "step": step,
                        "max_steps": 806,
                        "eval_loss": round(0.42 + 1.5 * math.exp(-step / 80), 4),
                    }
                )
            )
    log = ws.jobs / "20261027-230000-train.log"
    write(log, "\n".join(lines) + "\n")
    # earlier jobs for the history: building the dataset (done) and a test that was stopped
    earlier = []
    for name, kind, title, code, start, took, text in (
        (
            "20261027-190000-data.log",
            "data",
            "data demo",
            0,
            7 * 3600,
            3 * 3600 + 1200,
            "==> snapshot\n==> freeze\n==> router\n@@progress "
            + json.dumps(
                {
                    "role": "router",
                    "part": "paraphrases",
                    "done": 3000,
                    "target": 3000,
                    "rejected": 41,
                }
            )
            + "\n==> build\nok\n",
        ),
        (
            "20261026-210000-testgen.log",
            "testgen",
            "test test1",
            130,
            30 * 3600,
            1500,
            "==> testgen test1\n@@progress "
            + json.dumps(
                {"role": "test", "part": "router", "done": 40, "target": 96, "rejected": 7}
            )
            + "\nstopped\n",
        ),
    ):
        write(ws.jobs / name, text)
        started = time.time() - start
        earlier.append(
            json.dumps(
                {
                    "kind": kind,
                    "title": title,
                    "log": str(ws.jobs / name),
                    "started": started,
                    "finished": started + took,
                    "returncode": code,
                }
            )
        )
    write(ws.jobs / "history.jsonl", "\n".join(reversed(earlier)) + "\n")
    write(
        ws.jobs / "current.json",
        json.dumps(
            {
                "kind": "train",
                "title": "train e4b, e2b on demo",
                "log": str(log),
                "started": time.time() - 3 * 3600 - 742,
                "runner_pid": os.getpid(),
            }
        ),
    )
    return ws


class DemoHomeAssistant:
    """The machine's switch and plug for the header button - no real Home Assistant."""

    def __init__(self, connection) -> None:
        pass

    def entity_state(self, entity_id: str, timeout: float = 5) -> dict:
        return {"state": "on" if entity_id.startswith("switch.") else "412.6"}

    def entities(self, timeout: float = 10) -> list[dict]:
        return [
            {"entity_id": "switch.maszyna_gpu", "attributes": {"friendly_name": "Maszyna GPU"}},
            {
                "entity_id": "sensor.gniazdko_komputer_moc",
                "attributes": {"unit_of_measurement": "W"},
            },
        ]


def fake_nvidia_smi(folder: Path) -> None:
    script = folder / "nvidia-smi"
    script.write_text("#!/bin/sh\necho 'NVIDIA GeForce RTX 4090, 97, 20480, 24564, 68, 402.5'\n")
    script.chmod(0o755)
