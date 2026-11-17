"""Run one command, stream its output to a log file and record the exit code.

Started detached by the job manager, so a job keeps running when the browser, the panel or
the SSH connection is closed: ``python -m router_trainer.runner <state.json> <log> -- <cmd…>``.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HISTORY_FILE = "history.jsonl"


def run(state_path: Path, log_path: Path, cmd: list[str]) -> int:
    # "Stop" sends Ctrl+C to the whole process group: the command handles it (training saves a
    # checkpoint), the runner must survive to record the exit code (a Python handler, unlike
    # SIG_IGN, is not inherited by the child)
    signal.signal(signal.SIGINT, lambda *_: None)
    update(state_path, runner_pid=os.getpid())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        log.write(f"$ {' '.join(cmd)}\n".encode())
        log.flush()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # progress lines as they happen
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
        update(state_path, child_pid=process.pid)
        returncode = process.wait()
    update(state_path, returncode=returncode, finished=time.time())
    remember(state_path)
    return returncode


def update(path: Path, **values: object) -> None:
    """Change some fields of the state file. The runner and the studio both write it, so under a
    lock (else one writes back an old copy and the other's change is lost) and through a unique
    .tmp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        state.update(values)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)


def remember(path: Path) -> None:
    """The finished job goes to the history (jobs/history.jsonl next to the state file)."""
    state = json.loads(path.read_text(encoding="utf-8"))
    entry = {k: state.get(k) for k in ("kind", "title", "log", "started", "finished", "returncode")}
    with path.with_name(HISTORY_FILE).open("a", encoding="utf-8") as history:
        fcntl.flock(history, fcntl.LOCK_EX)
        history.write(json.dumps(entry) + "\n")


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[2] != "--":
        print("usage: runner <state.json> <log> -- <cmd...>", file=sys.stderr)
        return 2
    return run(Path(argv[0]), Path(argv[1]), argv[3:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
