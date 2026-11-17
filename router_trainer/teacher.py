"""The teacher: a big model in the trainer's own Ollama on the GPU box (default Gemma 4 26B).

It writes paraphrases, plans of commands and reference answers. It runs on the training
machine (tools/ollama, own model folder, own port), so the home Ollama is not loaded; before
training it is unloaded to free the graphics card.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.error
import urllib.request

from .config import TOOLS

OLLAMA_DIR = TOOLS / "ollama"
RETRIES = 2


def http(
    url: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 600,
    method: str | None = None,
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data, {"Content-Type": "application/json"}, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw.strip() else {}


def local_url(settings: dict[str, Any]) -> str:
    return f"http://127.0.0.1:{settings['ollama']['local_port']}"


def ollama_env(host: str, models: Path) -> dict[str, str]:
    env = dict(os.environ, OLLAMA_HOST=host, OLLAMA_MODELS=str(models))
    env["LD_LIBRARY_PATH"] = f"{OLLAMA_DIR / 'lib' / 'ollama'}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def start_local(settings: dict[str, Any], workspace_root: Path) -> str:
    """The trainer's Ollama (started detached when it is not running yet)."""
    url = local_url(settings)
    try:
        http(url, "/api/version", timeout=3)
        return url
    except OSError:
        pass
    binary = OLLAMA_DIR / "bin" / "ollama"
    if not binary.exists():
        raise FileNotFoundError(f"{binary} missing - run scripts/setup.sh on the GPU machine")
    models = workspace_root / "ollama-models"
    models.mkdir(parents=True, exist_ok=True)
    log = workspace_root / "jobs" / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    port = settings["ollama"]["local_port"]
    with log.open("ab") as out:
        subprocess.Popen(
            [str(binary), "serve"],
            env=ollama_env(f"127.0.0.1:{port}", models),
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    for _ in range(60):
        try:
            http(url, "/api/version", timeout=2)
            return url
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"the trainer's Ollama did not start ({log})")


class Teacher:
    """Chat with the teacher model: JSON (with a schema) or plain text."""

    def __init__(self, url: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.model = model

    def ensure(self) -> None:
        """Download the teacher model into the trainer's Ollama when it is missing."""
        names = {m["name"] for m in http(self.url, "/api/tags").get("models", [])}
        if self.model in names or f"{self.model}:latest" in names:
            return
        print(f".. pulling {self.model} into the trainer's Ollama", flush=True)
        http(self.url, "/api/pull", {"model": self.model, "stream": False}, timeout=7200)

    def _chat(self, body: dict[str, Any]) -> str:
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "30m", **body}
        for attempt in range(RETRIES + 1):
            try:
                return http(self.url, "/api/chat", body)["message"]["content"]
            except urllib.error.HTTPError:
                raise
            except (OSError, KeyError) as err:
                if attempt == RETRIES:
                    raise
                print(f"!! teacher: {err} - retry", flush=True)
                time.sleep(5)
        raise AssertionError("unreachable")

    def json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
        num_predict: int = 400,
        num_ctx: int = 8192,
        seed: int | None = None,
    ) -> dict[str, Any] | None:
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        }
        if seed is not None:
            options["seed"] = seed
        content = self._chat({"format": schema, "options": options, "messages": messages})
        try:
            value = json.loads(content)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def text(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        num_predict: int = 300,
        num_ctx: int = 8192,
    ) -> str:
        options = {"temperature": temperature, "num_predict": num_predict, "num_ctx": num_ctx}
        return " ".join(self._chat({"options": options, "messages": messages}).split())

    def unload(self) -> None:
        with contextlib.suppress(OSError):
            http(self.url, "/api/generate", {"model": self.model, "keep_alive": 0}, timeout=60)
