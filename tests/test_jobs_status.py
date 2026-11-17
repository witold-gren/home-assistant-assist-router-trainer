"""Background jobs, the workspace status and the log parser."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from router_trainer.config import Workspace
from router_trainer.jobs import JobManager
from router_trainer.status import parse_gpu, status
from router_trainer.ui import progress


def fake_cli(tmp_path, body: str) -> list[str]:
    script = tmp_path / "fake_cli.py"
    script.write_text(body)
    return [sys.executable, str(script)]


def test_job_runs_and_records_the_exit_code(tmp_path) -> None:
    manager = JobManager(tmp_path, fake_cli(tmp_path, "import sys; print('==> data'); sys.exit(0)"))
    state = manager.start("data", "data oct27", ["pipeline"])
    assert state.kind == "data"
    done = manager.wait(10)
    assert done.state == "ok" and done.returncode == 0
    log = Path(done.log).read_text()
    assert "==> data" in log and "--workspace" in log


def test_only_one_job_at_a_time(tmp_path) -> None:
    manager = JobManager(tmp_path, fake_cli(tmp_path, "import time; time.sleep(5)"))
    manager.start("train", "train", [])
    try:
        manager.start("data", "data", [])
    except RuntimeError as err:
        assert "still running" in str(err)
    else:
        raise AssertionError("expected JobBusy")
    finally:
        manager.stop()
        manager.wait(10)


def test_stop_sends_ctrl_c_and_shows_stopped(tmp_path) -> None:
    body = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGINT, lambda *a: sys.exit(130))\n"
        "print('ready', flush=True)\ntime.sleep(20)\n"
    )
    manager = JobManager(tmp_path, fake_cli(tmp_path, body))
    state = manager.start("train", "train", [])
    for _ in range(100):  # wait until the child installed its handler
        if "ready" in Path(state.log).read_text():
            break
        __import__("time").sleep(0.05)
    assert manager.stop()
    done = manager.wait(10)
    assert done.state == "stopped"
    assert JobManager(tmp_path).status().state == "stopped"  # survives a new manager


def test_status_reads_datasets_runs_and_log(tmp_path) -> None:
    ws = Workspace(tmp_path)
    (tmp_path / "datasets" / "oct27").mkdir(parents=True)
    (tmp_path / "datasets" / "oct27" / "card.json").write_text(
        json.dumps({"name": "oct27", "train": 10, "dev": 1, "roles": {"router": 11}})
    )
    run = tmp_path / "runs" / "oct27-e2b"
    (run / "checkpoints" / "checkpoint-100").mkdir(parents=True)
    (run / "params.json").write_text(json.dumps({"model_key": "e2b", "dataset": "/x/oct27"}))
    (run / "compare.json").write_text(json.dumps({"parts": {}}))
    manager = JobManager(
        tmp_path, fake_cli(tmp_path, 'print(\'@@metric {"step": 1, "loss": 2.0}\')')
    )
    manager.start("train", "train", [])
    manager.wait(10)
    first = status(ws)
    assert first["datasets"][0]["train"] == 10
    assert first["runs"][0]["checkpoint"] == "checkpoint-100" and first["runs"][0]["compare"]
    assert "@@metric" in first["log"]
    again = status(ws, first["log_offset"])
    assert again["log"] == ""


def test_parse_gpu() -> None:
    gpu = parse_gpu("NVIDIA GeForce RTX 4090, 97, 20100, 24564, 71, 410.5")
    assert gpu["utilization"] == 97 and gpu["memory_total"] == 24564
    assert parse_gpu("garbage") is None


LOG = """$ router-trainer pipeline
==> router
@@progress {"role": "router", "part": "paraphrase:kalendarz", "done": 25, "target": 300, "rejected": 2}
==> train oct27-e4b
@@info {"train": 9000, "dev": 300, "base": "unsloth/gemma-4-E4B-it"}
{'loss': 1.2}\r{'loss': 1.1}
@@metric {"step": 10, "max_steps": 500, "loss": 1.5}
@@metric {"step": 100, "max_steps": 500, "eval_loss": 0.9}
!! teacher: timed out - retry
@@result {"part": "router", "total": 379, "trained": 370, "base": 359}
@@metric {broken
"""


def test_progress_parses_markers() -> None:
    p = progress.parse(LOG)
    assert p.stage == "train oct27-e4b"
    assert p.counters["router/paraphrase:kalendarz"]["done"] == 25
    assert p.info["train"] == 9000
    assert [m["step"] for m in p.metrics] == [10, 100]
    assert p.results["router"]["trained"] == 370
    assert p.errors == ["!! teacher: timed out - retry"]


def test_tail_hides_markers_and_keeps_last_progress_state() -> None:
    text = progress.tail(LOG)
    assert "@@" not in text
    assert "{'loss': 1.1}" in text and "{'loss': 1.2}" not in text


def test_thin_keeps_eval_points() -> None:
    points = [{"step": i, "loss": 1.0} for i in range(1000)] + [{"step": 1000, "eval_loss": 0.5}]
    thinned = progress.thin(points, 100)
    assert len(thinned) <= 102 and thinned[-1]["eval_loss"] == 0.5
