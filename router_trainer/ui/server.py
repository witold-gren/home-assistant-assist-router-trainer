"""The training panel's state and actions, independent of HTTP (the studio serves them).

The whole road: the inputs from Home Assistant, the test, the dataset, training, export to the home
Ollama, validation, a "try it" box and the machine's power; jobs run detached on this machine.
router_trainer.studio.server puts it behind the login and the editor.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

from .. import ha_client, ha_inputs, power, router_source
from ..config import (
    REJECTED_MESSAGE,
    REPO,
    Workspace,
    load_settings,
    save_ha,
    token_path,
    token_rejected,
)
from ..pipeline import DATA_STEPS, check_name
from . import progress as progress_module
from .backend import LocalBackend
from .texts import LANGUAGES, texts

# the guide of the repository (docs/pl, docs/en), opened from the panel in a new tab
# the guide built by MkDocs (make docs; /app/site in the image), served at /docs/ behind the login
DOCS = Path(__file__).parents[2] / "site"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
}
POLL_SECONDS = 3.0
MACHINE_CACHE = 10.0  # seconds a Home Assistant answer about the machine's power is kept
MAX_TASK_LINES = 400
TRY_TIMEOUT = 900
MODEL_KEYS = {"epochs", "learning_rate", "lora_r", "lora_alpha"}


class Task:
    """A short local command sequence (the machine check) with its output."""

    def __init__(self, name: str, commands: list[list[str]]) -> None:
        self.name = name
        self.commands = commands
        self.lines: deque[str] = deque(maxlen=MAX_TASK_LINES)
        self.running = True
        self.code: int | None = None
        self.started = time.time()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        code = 0
        for command in self.commands:
            self.lines.append("$ " + " ".join(command[:3]) + (" …" if len(command) > 3 else ""))
            try:
                process = subprocess.Popen(
                    command,
                    cwd=REPO,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    errors="replace",
                )
            except OSError as err:
                self.lines.append(f"error: {err}")
                code = 127
                break
            assert process.stdout is not None
            for line in process.stdout:
                self.lines.append(line.rstrip("\n").rsplit("\r", 1)[-1])
            code = process.wait()
            if code != 0:
                break
        self.code = code
        self.running = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "running": self.running,
            "code": self.code,
            "started": self.started,
            "lines": list(self.lines)[-150:],
        }


class Panel:
    """State of the panel (independent of HTTP, so tests can drive it directly)."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.lock = threading.Lock()
        self.task: Task | None = None
        self.log = bytearray()
        self.log_path: str | None = None
        self.status: dict[str, Any] = {}
        self.error: str | None = None
        self._progress = progress_module.Progress()
        self._polled = 0.0
        self._backend = None
        self._machine_cache: tuple[float, dict[str, Any]] | None = None  # (time, power state)
        self._checked = False  # the job state was read (or failed to be) at least once
        self._refreshing = False  # a background check of the jobs and HA is running
        self.fetching: dict[str, Any] | None = None  # "Fetch from HA": running / done / error

    def backend(self) -> LocalBackend:
        if self._backend is None:
            self._backend = LocalBackend(self.ws)
        return self._backend

    # --- short local tasks ---------------------------------------------------------------------

    def _start_task(self, name: str, commands: list[list[str]]) -> None:
        if self.task is not None and self.task.running:
            raise RuntimeError(f"'{self.task.name}' is still running")
        self.task = Task(name, commands)

    def check(self) -> None:
        self._start_task("check", [self.backend().check_command()])

    # --- inputs from Home Assistant and the router code ------------------------------------------

    def fetch_from_ha(self) -> None:
        """Export from Home Assistant into workspace/inputs, in a thread (the page polls)."""
        if self.fetching and self.fetching.get("running"):
            raise RuntimeError("fetching from Home Assistant is still running")
        self.fetching = {"running": True, "started": time.time()}

        def work() -> None:
            try:
                summary = ha_inputs.fetch(self.ws)
                self.fetching = {"running": False, "ok": True, "summary": summary}
            except (ha_client.HaError, OSError, ValueError) as err:
                self.fetching = {"running": False, "ok": False, "error": str(err)}

        threading.Thread(target=work, name="ha-fetch", daemon=True).start()

    def router_state(self) -> dict[str, Any]:
        settings = load_settings(self.ws)
        last = ha_inputs.last(self.ws) or {}
        return router_source.state(
            self.ws.root, settings.get("router_repo_setting", "auto"), last.get("version")
        )

    def fetch_router(self, version: str | None) -> dict[str, Any]:
        """Clone the router code of the version Home Assistant runs (or the one given)."""
        version = version or (ha_inputs.last(self.ws) or {}).get("version")
        if not version:
            raise ValueError("fetch from Home Assistant first - its router version is not known")
        if self.poll(force=True)["running"]:
            raise RuntimeError("a job is running - change the router code when it ends")
        router_source.fetch(self.ws.root, str(version))
        return self.router_state()

    # --- jobs on the machine --------------------------------------------------------------------

    def start(self, data: dict[str, Any]) -> None:
        kind = str(data.get("kind", ""))
        if kind in ("data", "train"):
            dataset = check_name(str(data.get("dataset", "")).strip(), "dataset")
        if kind == "data":
            steps = [s for s in DATA_STEPS if s in (data.get("steps") or [])]
            if not steps:
                raise ValueError("choose at least one step")
            args = ["pipeline", "--steps", *steps, "--dataset", dataset]
            title = f"data {dataset}: {', '.join(steps)}"
        elif kind == "train":
            models = [str(m) for m in data.get("models") or []]
            if not models:
                raise ValueError("choose at least one model")
            steps = ["train", "export", "evaluate"] if data.get("then_export", True) else ["train"]
            args = ["pipeline", "--steps", *steps, "--dataset", dataset, "--models", *models]
            if data.get("resume"):
                args.append("--resume")
            overrides = [
                f"{k}={v}"
                for k, v in (data.get("set") or {}).items()
                if k in MODEL_KEYS and v not in (None, "")
            ]
            if overrides:
                args += ["--set", *overrides]
            title = f"train {', '.join(models)} on {dataset}"
        elif kind in ("export", "evaluate"):
            run = check_name(str(data.get("run", "")), "run")
            args, title = [kind, "--run", run], f"{kind} {run}"
        else:
            raise ValueError(f"unknown job {kind!r}")
        self.backend().start(kind, title, args)
        with self.lock:
            self._polled = 0.0

    def stop(self) -> None:
        self.backend().stop()
        with self.lock:
            self._polled = 0.0

    def try_text(self, text: str, models: list[str]) -> dict[str, Any]:
        text = " ".join(text.split())
        if not text or not models:
            raise ValueError("a sentence and at least one model")
        result = subprocess.run(
            self.backend().try_command(text, models),
            capture_output=True,
            text=True,
            timeout=TRY_TIMEOUT,
            check=False,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if result.returncode != 0 or not lines:
            raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or "try failed")
        return json.loads(lines[-1])

    # --- polling ---------------------------------------------------------------------------------

    def poll(self, force: bool = False) -> dict[str, Any]:
        """New log bytes and the state of the machine (at most every POLL_SECONDS).

        The machine is asked outside the lock: a machine that is off takes the SSH timeout to say
        so, and nothing else (the page, the log) waits for it."""
        with self.lock:
            if not force and time.time() - self._polled < POLL_SECONDS:
                return self._summary()
            self._polled = time.time()
            offset, log_path = len(self.log), self.log_path
            backend = self.backend()
        restart = False
        try:
            status = backend.status(offset)
            job = status.get("job")
            if job and job["log"] != log_path:
                # another job: read its log from the start
                status, restart = backend.status(0), True
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as err:
            with self.lock:
                self.error, self._checked = str(err) or type(err).__name__, True
                return self._summary()
        with self.lock:
            self.error, self._checked = None, True
            text = status.pop("log", None) or ""
            job = status.get("job")
            changed = False
            if restart and job and self.log_path != job["log"]:
                self.log = bytearray(text.encode())
                self.log_path = job["log"]
                changed = True
            elif not restart and text and len(self.log) == offset and self.log_path == log_path:
                # (a poll running at the same time may have added it already)
                self.log.extend(text.encode())
                changed = True
            if changed:
                self._progress = progress_module.parse(self.log.decode(errors="replace"))
            self.status = status
            return self._summary()

    def _summary(self) -> dict[str, Any]:
        """With the lock held: a job running on the machine, the last error, still checking."""
        job = self.status.get("job") or {}
        return {
            "running": bool(job.get("running")),
            "error": self.error,
            "checking": not self._checked,
        }

    def refresh_in_background(self) -> None:
        """Ask the machine and Home Assistant in a thread (one check at a time): the page always
        gets the last known state at once."""
        with self.lock:
            if self._refreshing:
                return
            self._refreshing = True

        def work() -> None:
            try:
                self.poll()
                self.machine()
            except Exception as err:  # said on the page, never "checking" for ever
                with self.lock:
                    self.error, self._checked = f"{type(err).__name__}: {err}", True
            finally:
                with self.lock:
                    self._refreshing = False

        threading.Thread(target=work, name="machine-check", daemon=True).start()

    def state(self, language: str | None = None) -> dict[str, Any]:
        """Everything the page shows - at once, from the last known state (never waits for SSH
        or Home Assistant; they are asked in the background)."""
        self.refresh_in_background()
        code, ui = texts(language)
        with self.lock:
            summary = self._summary()
            status = dict(self.status)
            log = progress_module.tail(self.log.decode(errors="replace"))
            progress = self._progress.as_dict()
        return {
            "ui": ui,
            "language": code,
            "languages": LANGUAGES,
            "ha": self.ha_state(),
            "inputs": ha_inputs.last(self.ws),
            "fetching": self.fetching,
            "router": self.router_state(),
            "machine": self.machine_cached(),
            "task": self.task.as_dict() if self.task else None,
            "error": summary["error"],
            "checking": summary["checking"],
            "status": status,
            "progress": progress,
            "log": log,
        }

    # --- the GPU machine's power, through Home Assistant (power.py) ------------------------------

    def save_power(self, data: dict[str, Any]) -> None:
        settings = power.PowerSettings(
            switch=str(data.get("switch", "")).strip(),
            sensor=str(data.get("sensor", "")).strip(),
            off_watts=data.get("off_watts") or 5,
        )
        power.save_power(self.ws, settings)
        self._machine_cache = None

    def _power_ready(self) -> tuple[power.PowerSettings, ha_client.Connection] | None:
        settings = power.load_power(self.ws)
        connection = ha_client.load_connection(self.ws)
        if not settings.ready or not connection.ready:
            return None
        return settings, connection

    def machine(self) -> dict[str, Any] | None:
        """The switch, the plug's power and whether the machine is on (header button); None
        when not set up. Asks Home Assistant at most every MACHINE_CACHE seconds."""
        ready = self._power_ready()
        if ready is None:
            return None
        if token_rejected(self.ws):  # never asked again with this token (ip_ban counts each 401)
            return {"machine": "rejected", "error": REJECTED_MESSAGE}
        cached = self._machine_cache
        if cached and time.time() - cached[0] < MACHINE_CACHE:
            return cached[1]
        settings, connection = ready
        try:
            answer = power.machine_state(
                ha_client.Client(connection, self.ws),
                settings,
                True,  # the panel runs on it
            )
        except ha_client.HaError as err:
            answer = {"machine": "unknown", "error": str(err)}
        self._machine_cache = (time.time(), answer)
        return answer

    def machine_cached(self) -> dict[str, Any] | None:
        """The last known machine state for the page ({"machine": "checking"} before the first
        answer); never waits for Home Assistant."""
        if self._power_ready() is None:
            return None
        if token_rejected(self.ws):
            return {"machine": "rejected", "error": REJECTED_MESSAGE}
        cached = self._machine_cache
        return cached[1] if cached else {"machine": "checking"}

    def switch_machine(self, on: bool) -> None:
        """Flip the machine's switch in Home Assistant (it shuts the system down before cutting
        the plug). Never switched off while a job runs on the machine."""
        ready = self._power_ready()
        if ready is None:
            raise ValueError(
                "set the machine's switch and power sensor first (step 1, Power of the GPU machine)"
            )
        if not on and self.poll(force=True)["running"]:
            raise RuntimeError(
                "a training job is running on the machine - stop it first or wait until it ends"
            )
        settings, connection = ready
        try:
            power.switch_machine(ha_client.Client(connection, self.ws), settings, on)
        except ha_client.HaError as err:
            raise RuntimeError(str(err)) from None
        self._machine_cache = None

    def ha_entities(self) -> dict[str, Any]:
        """Candidates for the power settings: switches and power sensors (W)."""
        entities = ha_client.Client(ha_client.load_connection(self.ws), self.ws).entities()

        def pick(test) -> list[dict[str, str]]:
            found = (
                {"id": e["entity_id"], "name": e.get("attributes", {}).get("friendly_name") or ""}
                for e in entities
                if test(e)
            )
            return sorted(found, key=lambda e: e["id"])

        return {
            "switches": pick(lambda e: e["entity_id"].startswith(("switch.", "input_boolean."))),
            "sensors": pick(
                lambda e: (
                    e["entity_id"].startswith("sensor.")
                    and e.get("attributes", {}).get("unit_of_measurement") == "W"
                )
            ),
        }

    def connect_ha(self, url: str, token: str | None) -> dict[str, Any]:
        """Check and save the HA address and token (the token never goes back to the page)."""
        self._machine_cache = None
        saved = save_ha(self.ws, url.strip(), (token or "").strip() or None)
        return {"url": saved["url"], **saved["checked"]}

    def ha_state(self) -> dict[str, Any]:
        settings = load_settings(self.ws)
        ha = settings["home_assistant"]
        return {
            "url": ha["url"],
            "token_set": token_path(self.ws, settings).exists(),
            "checked": ha.get("checked"),
            "rejected": token_rejected(self.ws),
            "power": asdict(power.load_power(self.ws)),
        }

    def action(self, data: dict[str, Any]) -> dict[str, Any] | None:
        name = data.get("action")
        if name == "ha":
            return self.connect_ha(str(data.get("url", "")), data.get("token"))
        if name == "testgen":
            test = check_name(str(data.get("name", "")).strip(), "test")
            self.backend().start("testgen", f"test {test}", ["testgen", "--name", test])
            with self.lock:
                self._polled = 0.0
            return None
        if name == "active_test":
            test = str(data.get("name", ""))
            if test != "ha":
                check_name(test, "test")
            result = self.backend().cli_json("tests", "--active", test)
            with self.lock:
                self._polled = 0.0
            return result
        if name in ("review_list", "review"):
            test = str(data.get("name", ""))
            if test != "ha":
                check_name(test, "test")
            args = ["review", "--name", test]
            if name == "review":
                args += [
                    "--case",
                    str(data.get("case", "")),
                    "--reject" if data.get("rejected") else "--keep",
                ]
            return self.backend().cli_json(*args)
        if name == "power_settings":
            self.save_power(data)
            return None
        if name in ("machine_on", "machine_off"):
            self.switch_machine(name == "machine_on")
            return None
        if name == "fetch":
            self.fetch_from_ha()
            return None
        if name == "router_fetch":
            return self.fetch_router(data.get("version"))
        if name == "check":
            self.check()
        elif name == "start":
            self.start(data)
        elif name == "stop":
            self.stop()
        elif name == "try":
            return self.try_text(
                str(data.get("text", "")), [str(m) for m in data.get("models") or []]
            )
        else:
            raise ValueError(f"unknown action '{name}'")
        return None
