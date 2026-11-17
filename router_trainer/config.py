"""Settings (workspace/trainer.yaml) and the workspace layout.

The workspace holds everything private: copies of your HA files, the home snapshot, generated
data, datasets, trained models and results. Missing settings fall back to
``trainer.example.yaml`` (shipped with the package), so an older trainer.yaml keeps working.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any
import urllib.error
import urllib.request

import yaml

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parent
# the trainer's Ollama and llama.cpp, and the training Python (.venv-train); in the container
# they live in /opt, outside the code (ROUTER_TRAINER_TOOLS, ROUTER_TRAINER_TRAIN_PYTHON)
TOOLS = Path(os.environ.get("ROUTER_TRAINER_TOOLS") or REPO / "tools")
TRAIN_PYTHON = Path(
    os.environ.get("ROUTER_TRAINER_TRAIN_PYTHON") or REPO / ".venv-train" / "bin" / "python"
)
EXAMPLE = PACKAGE / "trainer.example.yaml"
CONFIG_FILE = "trainer.yaml"
# the panel's HA connection: url and token file, kept apart so trainer.yaml keeps its comments
HA_FILE = "home_assistant.json"
TOKEN_FILE = "ha_token"
# the container keeps it on the data volume (ROUTER_TRAINER_WORKSPACE=/data/workspace)
DEFAULT_WORKSPACE = Path(os.environ.get("ROUTER_TRAINER_WORKSPACE") or REPO / "workspace")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """``base`` with ``override`` on top (nested dicts merged, everything else replaced)."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Workspace:
    """Folders and files of one workspace."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()

    def path(self, relative: str | Path) -> Path:
        path = Path(relative).expanduser()
        return path if path.is_absolute() else self.root / path

    @property
    def config_file(self) -> Path:
        return self.root / CONFIG_FILE

    @property
    def ha_file(self) -> Path:
        return self.root / HA_FILE

    @property
    def snapshot(self) -> Path:
        return self.root / "home" / "snapshot.json"

    @property
    def holdout(self) -> Path:
        return self.root / "holdout" / "holdout.json"

    @property
    def generated(self) -> Path:
        return self.root / "generated"

    @property
    def datasets(self) -> Path:
        return self.root / "datasets"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    def dataset(self, name: str) -> Path:
        return self.datasets / name

    def run(self, name: str) -> Path:
        return self.runs / name


def init_workspace(root: Path) -> Workspace:
    """Create the workspace with a copy of the example settings (an existing file is kept)."""
    workspace = Workspace(root)
    workspace.root.mkdir(parents=True, exist_ok=True)
    if not workspace.config_file.exists():
        shutil.copy(EXAMPLE, workspace.config_file)
    return workspace


def load_settings(workspace: Workspace) -> dict[str, Any]:
    """The example, trainer.yaml on top, and the HA connection saved by the panel on top."""
    settings = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    if workspace.config_file.exists():
        own = yaml.safe_load(workspace.config_file.read_text(encoding="utf-8")) or {}
        settings = deep_merge(settings, own)
    if workspace.ha_file.exists():
        ha = json.loads(workspace.ha_file.read_text(encoding="utf-8"))
        settings = deep_merge(settings, {"home_assistant": ha})
    # `auto`: the router version fetched for the one Home Assistant runs (router_source.py)
    from .router_source import resolve

    settings["router_repo_setting"] = str(settings.get("router_repo", "auto"))
    settings["router_repo"] = str(resolve(workspace.root, settings["router_repo_setting"]))
    return settings


def token_path(workspace: Workspace, settings: dict[str, Any]) -> Path:
    """The HA token file; a relative path is inside the workspace (as the panel saves it)."""
    return workspace.path(settings["home_assistant"]["token_file"])


REJECTED_KEY = "token_rejected"  # in workspace/home_assistant.json
REJECTED_MESSAGE = (
    "Home Assistant rejected the token - not asked again until it is connected anew "
    "(step 1, Connect to HA)"
)


def token_rejected(workspace: Workspace) -> bool:
    """Home Assistant answered 401 to the saved token. Every 401 is a failed login for HA's
    ip_ban, so nothing asks again until "Connect" in step 1 checks the connection anew."""
    return bool(read_ha_file(workspace).get(REJECTED_KEY))


def mark_token_rejected(workspace: Workspace) -> None:
    if workspace.ha_file.exists():
        write_ha_file(workspace, {**read_ha_file(workspace), REJECTED_KEY: True})


def check_ha(url: str, token: str, timeout: float = 10) -> dict[str, Any]:
    """Home Assistant answers with this token: its name and version (ValueError when not)."""
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Home Assistant address: http://… or https://…")
    from .ha_client import _direct_url  # homeassistant.local: IPv4 at once (macOS mDNS)

    address, host = _direct_url(f"{url}/api/config")
    request = urllib.request.Request(address, headers={"Authorization": f"Bearer {token}", **host})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as err:
        if err.code == 401:
            raise ValueError("Home Assistant rejected the token") from None
        if err.code == 403:
            from .ha_client import explain

            raise ValueError(explain(403, "")) from None
        raise ValueError(f"Home Assistant: HTTP {err.code}") from None
    except OSError as err:
        raise ValueError(f"Home Assistant not reachable at {url}: {err}") from None
    return {"name": data.get("location_name"), "version": data.get("version")}


def save_ha(workspace: Workspace, url: str, token: str | None) -> dict[str, Any]:
    """Check the connection and save it (token in workspace/ha_token, mode 600). Without a new
    token the saved one is checked with the new address. The trainer only reads with the token
    (entities, areas, aliases, calendars); the one exception is the GPU machine's switch, flipped
    on request when its power settings are set (power.py)."""
    workspace.root.mkdir(parents=True, exist_ok=True)
    token_file = workspace.root / TOKEN_FILE
    saved_token = not token
    if not token:
        if not token_file.exists():
            raise ValueError("paste a long-lived access token (HA profile -> Security)")
        token = token_file.read_text(encoding="utf-8").strip()
    try:
        info = check_ha(url, token.strip())
    except ValueError as err:
        if saved_token and "rejected the token" in str(err):
            mark_token_rejected(workspace)  # the saved one: nothing asks with it any more
        raise
    # created readable by the owner only
    descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token.strip() + "\n")
    token_file.chmod(0o600)
    data = {"url": url.rstrip("/"), "token_file": TOKEN_FILE, "checked": info}
    # other settings kept in the same file (the machine's power, see power.py) stay
    kept = {k: v for k, v in read_ha_file(workspace).items() if k != REJECTED_KEY}  # asked again
    data = {**kept, **data}
    write_ha_file(workspace, data)
    return data


def read_ha_file(workspace: Workspace) -> dict[str, Any]:
    """workspace/home_assistant.json as saved by the panel ({} when missing)."""
    if not workspace.ha_file.exists():
        return {}
    return json.loads(workspace.ha_file.read_text(encoding="utf-8")) or {}


def write_ha_file(workspace: Workspace, data: dict[str, Any]) -> None:
    """home_assistant.json, readable by the owner only (it names the token file)."""
    workspace.root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(workspace.ha_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=1) + "\n")
    workspace.ha_file.chmod(0o600)


def router_repo(settings: dict[str, Any]) -> Path:
    """The router repository; load_settings resolves `auto` already (here: without a workspace,
    the checkout next to the trainer)."""
    from .router_source import resolve

    return resolve(REPO, str(settings["router_repo"]))


def model_settings(settings: dict[str, Any], model: str) -> dict[str, Any]:
    try:
        return settings["models"][model]
    except KeyError:
        known = ", ".join(settings.get("models", {}))
        raise ValueError(f"unknown model {model!r} (trainer.yaml models: {known})") from None


def ollama_name(settings: dict[str, Any], model: str, run: str) -> str:
    """Name of the trained model in Ollama: ``assist-router-e4b-ft:<run>``."""
    return f"{settings['export']['name'].format(model=model)}:{run}"
