"""The studio's jobs run the REAL command line, exactly as the panel starts them: JobManager's own command
(python -m router_trainer.cli), through the runner, no stand-in CLI. A cli.py that does nothing when started
with -m would make every job "succeed" in 0.1 s with an empty log; these tests catch that."""

from __future__ import annotations

import subprocess
import sys
import time

from router_trainer.jobs import JobManager


def finished(jobs: JobManager, timeout: float = 60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.status()
        if status is not None and not status.running and status.returncode is not None:
            return status
        time.sleep(0.1)
    raise AssertionError("the job did not finish")


def test_the_module_answers_help_and_rejects_a_wrong_argument() -> None:
    ok = subprocess.run(
        [sys.executable, "-m", "router_trainer.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ok.returncode == 0 and "testgen" in ok.stdout
    wrong = subprocess.run(
        [sys.executable, "-m", "router_trainer.cli", "no-such-command"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert wrong.returncode != 0 and "invalid choice" in wrong.stderr


def test_a_job_started_like_the_panel_does_runs_the_real_cli(tmp_path) -> None:
    jobs = JobManager(tmp_path / "ws")
    assert "router_trainer.cli" in jobs.command  # the default: the real CLI, not a test double
    jobs.start("init", "init", ["init"])
    status = finished(jobs)
    assert status.state == "ok"
    assert (tmp_path / "ws" / "trainer.yaml").is_file()  # the job really did its work
    log = (tmp_path / "ws" / "jobs").glob("*-init.log")
    assert any(path.read_text(encoding="utf-8").strip() for path in log)


def test_a_job_with_a_wrong_argument_fails_with_its_message(tmp_path) -> None:
    jobs = JobManager(tmp_path / "ws")
    jobs.start("check", "check", ["no-such-command"])
    status = finished(jobs)
    assert status.state == "failed" and status.returncode not in (0, None)
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "ws" / "jobs").glob("*.log"))
    assert "invalid choice" in text


def test_reviewing_a_test_not_fetched_yet_says_what_to_do(tmp_path) -> None:
    """A fresh workspace on the machine: the panel shows one clear line, not a Python traceback."""
    jobs_ws = tmp_path / "ws"
    subprocess.run(
        [sys.executable, "-m", "router_trainer.cli", "--workspace", str(jobs_ws), "init"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "router_trainer.cli",
            "--workspace",
            str(jobs_ws),
            "review",
            "--name",
            "ha",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 1
    assert "Traceback" not in out.stderr
    assert "fetch from Home Assistant (step 1)" in out.stderr
