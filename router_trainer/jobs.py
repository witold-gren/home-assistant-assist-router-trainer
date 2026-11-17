"""Background jobs: one ``router-trainer`` command at a time (there is one GPU).

State lives in workspace/jobs/current.json, so the panel (or the SSH connection to the GPU
machine) can be closed and opened again while a job runs. Stop = Ctrl+C to the job's process
group: training saves a checkpoint and Resume continues from it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

from .runner import HISTORY_FILE, update

STOPPED_CODES = (130, -2)
MAX_READ = 2_000_000  # bytes of log returned per poll


@dataclass(frozen=True)
class JobStatus:
    kind: str
    title: str
    running: bool
    returncode: int | None
    started: float | None
    finished: float | None
    log: str  # path of the log file

    @property
    def state(self) -> str:
        if self.running:
            return "running"
        if self.returncode is None:
            return "interrupted"  # the runner vanished (a container restart): no exit code
        if self.returncode == 0:
            return "ok"
        if self.returncode in STOPPED_CODES:
            return "stopped"
        return "failed"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "state": self.state}


class JobBusy(RuntimeError):
    pass


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_log(path: Path, offset: int) -> bytes:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(MAX_READ)
    except OSError:
        return b""


class JobManager:
    def __init__(self, workspace: Path, command: list[str] | None = None) -> None:
        self.workspace = Path(workspace)
        self.dir = self.workspace / "jobs"
        self.state_path = self.dir / "current.json"
        # the CLI itself, so the panel and the command line do exactly the same thing
        self.command = command or [sys.executable, "-m", "router_trainer.cli"]
        self._processes: list[subprocess.Popen] = []

    def _state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _reap(self) -> None:
        # finished runners started by this process would otherwise stay as zombies
        self._processes = [p for p in self._processes if p.poll() is None]

    def running(self) -> bool:
        self._reap()
        state = self._state()
        return bool(state) and "returncode" not in state and pid_alive(state.get("runner_pid"))

    def start(self, kind: str, title: str, args: list[str]) -> JobStatus:
        if self.running():
            raise JobBusy(f"{self._state().get('title')} is still running")
        self.dir.mkdir(parents=True, exist_ok=True)
        log_path = self.dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}.log"
        cmd = [*self.command, "--workspace", str(self.workspace), *args]
        if self.state_path.exists():
            self.state_path.unlink()
        update(self.state_path, kind=kind, title=title, log=str(log_path), started=time.time())
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "router_trainer.runner",
                str(self.state_path),
                str(log_path),
                "--",
                *cmd,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # own process group, survives the panel
        )
        self._processes.append(process)
        deadline = time.time() + 5  # the runner records its pid itself
        while (
            "runner_pid" not in self._state() and process.poll() is None and time.time() < deadline
        ):
            time.sleep(0.02)
        status = self.status()
        assert status is not None
        return status

    def stop(self) -> bool:
        if not self.running():
            return False
        try:
            os.killpg(self._state()["runner_pid"], signal.SIGINT)
        except (ProcessLookupError, KeyError):
            return False
        return True

    def status(self) -> JobStatus | None:
        self._reap()
        state = self._state()
        if not state:
            return None
        running = "returncode" not in state and pid_alive(state.get("runner_pid"))
        returncode = state.get("returncode")
        return JobStatus(
            kind=state.get("kind", ""),
            title=state.get("title", ""),
            running=running,
            returncode=returncode,
            started=state.get("started"),
            finished=state.get("finished"),
            log=state.get("log", ""),
        )

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Earlier jobs, newest first: kind, title, times, state; an interrupted one too."""
        entries = []
        path = self.dir / HISTORY_FILE
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        current = self.status()
        if current and not current.running and current.state == "interrupted":
            entries.append({**current.as_dict(), "returncode": None})
        out = []
        for entry in entries:
            status = JobStatus(
                kind=entry.get("kind") or "",
                title=entry.get("title") or "",
                running=False,
                returncode=entry.get("returncode"),
                started=entry.get("started"),
                finished=entry.get("finished"),
                log=entry.get("log") or "",
            )
            out.append(status.as_dict())
        out.sort(key=lambda e: e.get("started") or 0, reverse=True)
        return out[:limit]

    def log_text(self, log: str) -> str:
        """The whole log of a job (only files of the jobs folder)."""
        path = Path(log).resolve()
        if self.dir.resolve() not in path.parents or not path.is_file():
            raise ValueError("not a log of this workspace")
        return path.read_bytes()[-MAX_READ:].decode("utf-8", "replace")

    def wait(self, timeout: float = 30.0) -> JobStatus | None:
        """Block until the current job ends (tests and scripts)."""
        deadline = time.time() + timeout
        while self.running() and time.time() < deadline:
            time.sleep(0.1)
        return self.status()
