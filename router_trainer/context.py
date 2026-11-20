"""What every data step needs: workspace, settings, the integration, router.yaml, the frozen
test, the home snapshot and (on demand) the teacher."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
from types import ModuleType
from typing import Any

from . import holdout as holdout_module, integration, languages, teacher as teacher_module
from .config import (
    REJECTED_MESSAGE,
    Workspace,
    load_settings,
    router_repo,
    token_path,
    token_rejected,
)


@dataclass
class Context:
    ws: Workspace
    settings: dict[str, Any]
    integ: integration.Integration
    config: Any  # RouterConfig of the integration
    pack: ModuleType  # trainer language pack
    _teachers: dict[str, Any] = field(default_factory=dict, repr=False)

    def input(self, name: str) -> Path:
        return self.ws.path(self.settings["inputs"][name])

    def tests(self) -> dict[str, Any]:
        """The active test (the HA test file or a generated one) without rejected cases."""
        from .testset import store

        return store.load(self.ws, self.settings)

    def test_data(self) -> Path:
        """The snapshot of the active test."""
        from .testset import store

        return store.paths(self.ws, self.settings)[1]

    def holdout(self) -> holdout_module.Holdout:
        return holdout_module.load(self.ws.holdout)

    def home_data(self) -> dict[str, Any]:
        if not self.ws.snapshot.exists():
            raise FileNotFoundError(
                f"{self.ws.snapshot} missing - take the home snapshot first "
                "(router-trainer snapshot)"
            )
        return json.loads(self.ws.snapshot.read_text(encoding="utf-8"))["home"]

    def rng(self, salt: str) -> random.Random:
        return random.Random(f"{self.settings['generate']['seed']}:{salt}")

    def teacher(self, role: str = "writer") -> Any:
        """The teacher of a role: ``writer`` writes the data, ``judge`` checks and labels it
        (trainer.yaml ``teacher.<role>``: the trainer's Ollama, an API, Claude or by hand)."""
        if role not in self._teachers:
            self._teachers[role] = teacher_module.make(self.settings, self.ws.root, role)
        return self._teachers[role]

    def token(self) -> str:
        if token_rejected(self.ws):  # each 401 is a failed login for HA's ip_ban
            raise RuntimeError(REJECTED_MESSAGE)
        path = token_path(self.ws, self.settings)
        if not path.exists():
            raise FileNotFoundError(
                f"HA token file {path} missing - connect Home Assistant in the panel (step 1)"
            )
        return path.read_text(encoding="utf-8").strip()


def make(ws: Workspace) -> Context:
    settings = load_settings(ws)
    integ = integration.load(router_repo(settings))
    router_file = ws.path(settings["inputs"]["router"])
    if not router_file.exists():
        raise FileNotFoundError(f"{router_file} missing - send the inputs first (Send step)")
    use_home_language(ws)  # as the integration in HA; `language:` of router.yaml still wins
    config = integ.load_config(router_file)
    return Context(ws, settings, integ, config, languages.get(integ.lang.CODE))


def use_home_language(ws: Workspace) -> bool:
    """The language pack of Home Assistant's language (from the last fetch), as Assist Router
    does at setup - when there is a pack for it."""
    from importlib import import_module

    from . import ha_inputs

    language = (ha_inputs.last(ws) or {}).get("language")
    if not language:
        return False
    packs = import_module("custom_components.assist_router.languages")
    return bool(packs.set_language(str(language)))
