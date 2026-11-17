"""The work happens on this machine: the panel runs in the trainer's container on the GPU machine.

The panel speaks the same CLI as a terminal would: ``router-trainer status`` (in-process here),
``job start``/``job stop`` (detached jobs that outlive a page reload) and ``try``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from ..config import Workspace

CHECK_SCRIPT = (
    'echo "host: $(hostname)"; '
    "(nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader "
    "2>/dev/null | sed 's/^/gpu: /') || echo 'gpu: none (nvidia-smi not found - is the container "
    "started with the GPU?)'; "
    "echo \"free disk: $(df -h . | awk 'NR==2{print $4}')\"; "
    'for tool in git curl; do command -v $tool >/dev/null && echo "$tool: yes" '
    '|| echo "$tool: MISSING"; done; '
    "[ -x .venv/bin/python ] && echo 'app env (.venv): yes' "
    "|| echo 'app env (.venv): MISSING - rebuild the image (make update)'; "
    "[ -x .venv-train/bin/python ] && echo 'training env (.venv-train): yes' "
    "|| echo 'training env (.venv-train): MISSING - rebuild the image (make update)'; "
    '[ -x tools/ollama/bin/ollama ] && echo "trainer Ollama: '
    '$(tools/ollama/bin/ollama --version 2>/dev/null | tail -1)" '
    "|| echo 'trainer Ollama: MISSING - rebuild the image (make update)'"
)


class LocalBackend:
    """Everything on this computer."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws

    def cli(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "router_trainer.cli", "--workspace", str(self.ws.root), *args]

    def status(self, offset: int) -> dict[str, Any]:
        from ..status import status

        return status(self.ws, offset)

    def start(self, kind: str, title: str, args: list[str]) -> None:
        from ..jobs import JobManager

        JobManager(self.ws.root).start(kind, title, args)

    def stop(self) -> None:
        from ..jobs import JobManager

        JobManager(self.ws.root).stop()

    def check_command(self) -> list[str]:
        return ["bash", "-c", CHECK_SCRIPT]

    def try_command(self, text: str, models: list[str]) -> list[str]:
        return self.cli("try", "--text", text, "--models", *models)

    def cli_json(self, *args: str) -> Any:
        """A short CLI command on this computer, its JSON answer."""
        result = subprocess.run(
            self.cli(*args), capture_output=True, text=True, timeout=60, check=False
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip()[-400:] or "command failed")
        return json.loads(result.stdout)
