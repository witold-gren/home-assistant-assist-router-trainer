"""The Assist Router code the trainer uses: the same version as the one installed in Home Assistant.

The trainer imports the router's prompts, schemas and test tools, so a model learns exactly what
the integration sends. ``router_repo: auto`` (the default) uses ``<workspace>/router/<tag>``, a
copy of the public repository at the tag of the version Home Assistant runs; "Fetch the router
version of HA" clones it (no image rebuild). A local checkout next to the trainer is used while
nothing is fetched yet (development on a computer with both repositories).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

REPOSITORY = "https://github.com/witold-gren/home-assistant-assist-router.git"
FOLDER = "router"
CURRENT = "current"  # file in <workspace>/router: the tag in use
VERSION = re.compile(r"^\d+\.\d+\.\d+([.-]?[a-z0-9]+)?$")
# the router's test requirements baked into the Docker image (to say when they changed)
IMAGE_REQUIREMENTS = os.environ.get("ROUTER_TRAINER_IMAGE_REQUIREMENTS", "")
SIBLING = Path(__file__).resolve().parents[2] / "home-assistant-assist-router"


def folder(root: Path) -> Path:
    return Path(root) / FOLDER


def version_of(repo: Path) -> str | None:
    """The integration version of a router checkout (its manifest), None when it is not one."""
    manifest = Path(repo) / "custom_components" / "assist_router" / "manifest.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return None


def current(root: Path) -> Path | None:
    """The fetched checkout in use (None when nothing was fetched)."""
    marker = folder(root) / CURRENT
    try:
        tag = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    path = folder(root) / tag
    return path if tag and version_of(path) else None


def resolve(root: Path, configured: str) -> Path:
    """The router repository for ``router_repo`` of trainer.yaml (``auto`` or a path)."""
    if str(configured).strip() != "auto":
        path = Path(configured).expanduser()
        trainer = Path(__file__).resolve().parents[1]
        return path if path.is_absolute() else (trainer / path).resolve()
    return current(root) or SIBLING


def check_version(version: str) -> str:
    version = str(version).strip().removeprefix("v")
    if not VERSION.match(version):
        raise ValueError(f"not a version: {version!r}")
    return version


def fetch(root: Path, version: str, runner=subprocess.run) -> Path:
    """Clone the public router repository at ``v<version>`` and use it from now on."""
    version = check_version(version)
    tag = f"v{version}"
    target = folder(root) / tag
    if version_of(target) != version:
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        result = runner(
            ["git", "clone", "--depth", "1", "--branch", tag, REPOSITORY, str(target)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip().splitlines()
            raise RuntimeError(f"git clone {tag}: {message[-1] if message else 'failed'}")
        if version_of(target) != version:
            raise RuntimeError(f"{tag} of the router repository is not version {version}")
    (folder(root) / CURRENT).write_text(tag + "\n", encoding="utf-8")
    return target


def requirements_changed(repo: Path) -> bool:
    """The router's test requirements differ from those installed in the image (rebuild it)."""
    if not IMAGE_REQUIREMENTS:
        return False
    try:
        installed = Path(IMAGE_REQUIREMENTS).read_bytes()
        used = (Path(repo) / "requirements_test.txt").read_bytes()
    except OSError:
        return False
    return hashlib.sha256(installed).digest() != hashlib.sha256(used).digest()


def state(root: Path, configured: str, ha_version: str | None) -> dict[str, Any]:
    """For the panel: the version in use, the one in HA and whether they match."""
    repo = resolve(root, configured)
    used = version_of(repo)
    return {
        "mode": "auto" if str(configured).strip() == "auto" else "path",
        "path": str(repo),
        "version": used,
        "ha_version": ha_version,
        "matches": bool(used and ha_version and used == ha_version),
        "rebuild": requirements_changed(repo) if used else False,
    }
