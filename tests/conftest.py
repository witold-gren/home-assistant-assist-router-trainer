"""Fixtures: a small made-up home (the household of the router's example config) and a
context with the real integration - no Home Assistant, Ollama or GPU needed."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
from types import ModuleType
from typing import Any

import pytest
import yaml

from router_trainer import holdout, integration, languages
from router_trainer.config import EXAMPLE, Workspace, deep_merge, router_repo

ROUTER_YAML = """
household: "Domownicy: Tomek (tata), Ania (mama), dzieci: Ola i Kuba."
people:
  tomek: {name: Tomek, match: "tom|tat(a|y)"}
  ania: {name: Ania, match: "ani|mam(a|y)"}
  ola: {name: Ola, match: "ol(a|i)"}
topics:
  kalendarz:
    description: wydarzenia z kalendarzy
    examples: ["Co mamy jutro?"]
    entities: ["calendar.*"]
  sterowanie:
    description: polecenia sterowania urządzeniami
    examples: ["Zgaś światło w kuchni"]
    control: true
  wiedza:
    description: wiedza ogólna
    examples: ["Kim był Kopernik?"]
    search: wikipedia
  niezrozumiale:
    description: bełkot
    examples: ["Ta no ten"]
    unclear: true
  pogoda:
    description: pogoda
    examples: ["Czy będzie padać?"]
    entities: ["weather.*"]
  inne:
    description: wszystko inne
    examples: ["Opowiedz kawał"]
"""

HOME = {
    "actions": {"Ekspres - zrób kawę": "Parzy kawę", "Dobranoc": "Gasi światła"},
    "targets": [
        {"entity_id": "light.kuchnia", "name": "Kuchnia Światło", "domain": "light",
         "device_class": None, "area": "Kuchnia", "names": ["Kuchnia Światło"]},
        {"entity_id": "light.salon_lampa", "name": "Lampa przy kanapie", "domain": "light",
         "device_class": None, "area": "Salon", "names": ["Lampa przy kanapie", "lampka"]},
        {"entity_id": "cover.salon", "name": "Salon Roleta", "domain": "cover",
         "device_class": "shutter", "area": "Salon", "names": ["Salon Roleta"]},
        {"entity_id": "media_player.salon", "name": "Salon Głośnik", "domain": "media_player",
         "device_class": "speaker", "area": "Salon", "names": ["Salon Głośnik"]},
        {"entity_id": "climate.salon", "name": "Salon Klimatyzacja", "domain": "climate",
         "device_class": None, "area": "Salon", "names": ["Salon Klimatyzacja"]},
        {"entity_id": "switch.ekspres", "name": "Ekspres", "domain": "switch",
         "device_class": None, "area": "Kuchnia", "names": ["Ekspres", "ekspres do kawy"]},
        {"entity_id": "vacuum.robot", "name": "Odkurzacz", "domain": "vacuum",
         "device_class": None, "area": None, "names": ["Odkurzacz"]},
        {"entity_id": "todo.zakupy", "name": "Lista zakupów", "domain": "todo",
         "device_class": None, "area": None, "names": ["Lista zakupów"]},
        {"entity_id": "script.ekspres", "name": "Ekspres - zrób kawę", "domain": "script",
         "device_class": None, "area": None, "names": ["Ekspres - zrób kawę"]},
        {"entity_id": "scene.dobranoc", "name": "Dobranoc", "domain": "scene",
         "device_class": None, "area": None, "names": ["Dobranoc"]},
    ],
    "areas": {"Kuchnia": "Kuchnia", "Salon": "Salon", "pokój dzienny": "Salon"},
    "floors": {},
    "domains": ["climate", "cover", "light", "media_player", "scene", "script", "switch",
                "todo", "vacuum"],
}  # fmt: skip

TESTS = {
    "router": [["Włącz światło w kuchni", "sterowanie"], ["Co Ola ma jutro?", "kalendarz"]],
    "control": {
        "household": "inny opis domu",
        "cases": [{"text": "Zgaś lampkę w salonie", "expect": {"intent": "HassTurnOff"}}],
    },
    "answers": {"cases": [{"name": "a", "question": "Ile pieniędzy ma Kuba?", "data": "x"}]},
    "real": {"cases": [{"name": "r", "topic": "kalendarz", "question": "Co jest w piątek?"}]},
    "wiki_answers": {
        "cases": [{"name": "w", "source": "kopernik", "question": "Kim był Kopernik?"}]
    },
    "wiki": {"kopernik": "Mikołaj Kopernik"},
}


def router_available() -> bool:
    try:
        settings = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        return (router_repo(settings) / "custom_components" / "assist_router").is_dir()
    except OSError:
        return False


def is_loopback(host: str | None) -> bool:
    import ipaddress

    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def only_this_computer(monkeypatch):
    """Tests talk to fake servers on 127.0.0.1 only (gpu-studio.md section 9).

    The settings hold http://homeassistant.local:8123 and the Jetson's Ollama; a request a test forgot to
    fake would reach the real Home Assistant (every 401 is a failed login for its ip_ban) or start a real
    model. Blocked at the socket, so urllib, aiohttp and the WebSocket all stop the same way.
    """
    import socket

    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if not is_loopback(name):
            raise socket.gaierror(f"tests never leave this computer ({name})")
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(address[0]):
            raise ConnectionRefusedError(f"tests never leave this computer ({address[0]})")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture(autouse=True)
def harmless_power_off(monkeypatch) -> list[str]:
    """Switching the machine off never leaves a test (gpu-studio.md section 9): a Home Assistant service call
    to anything but a fake server on 127.0.0.1 is only written down here."""
    from urllib import parse

    from router_trainer import ha_client

    calls: list[str] = []
    if not isinstance(ha_client.Client, type):
        return calls  # the demo's made-up home replaced the client already (scripts/studio_demo.py)
    real_call_service = ha_client.Client.call_service

    def call_service(self, domain, service, entity_id, timeout=10):
        if is_loopback(parse.urlsplit(self.connection.url).hostname):
            return real_call_service(self, domain, service, entity_id, timeout)
        calls.append(f"{domain}.{service} {entity_id}")
        return None

    monkeypatch.setattr(ha_client.Client, "call_service", call_service)
    return calls


needs_router = pytest.mark.skipif(
    not router_available(), reason="Assist Router repository next to the trainer needed"
)


@pytest.fixture(scope="session")
def integ() -> integration.Integration:
    if not router_available():
        pytest.skip("Assist Router repository next to the trainer needed")
    settings = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    return integration.load(router_repo(settings))


@pytest.fixture
def home_data() -> dict[str, Any]:
    return json.loads(json.dumps(HOME))


@dataclass
class FakeContext:
    """The Context of the data steps without HA, the teacher or files from the user."""

    ws: Workspace
    settings: dict[str, Any]
    integ: integration.Integration
    config: Any
    pack: ModuleType
    home: dict[str, Any]
    tests_data: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(TESTS)))
    teacher_obj: Any = None

    def input(self, name: str) -> Path:
        return self.ws.path(self.settings["inputs"][name])

    def tests(self) -> dict[str, Any]:
        return self.tests_data

    def test_data(self) -> Path:
        return self.ws.path(self.settings["inputs"]["test_data"])

    def holdout(self) -> holdout.Holdout:
        return holdout.Holdout(holdout.test_sentences(self.tests_data))

    def home_data(self) -> dict[str, Any]:
        return self.home

    def rng(self, salt: str) -> random.Random:
        return random.Random(f"42:{salt}")

    def teacher(self) -> Any:
        return self.teacher_obj


@pytest.fixture
def ctx(tmp_path: Path, integ: integration.Integration, home_data: dict[str, Any]) -> FakeContext:
    settings = deep_merge(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")), {})
    ws = Workspace(tmp_path / "workspace")
    ws.root.mkdir(parents=True)
    config = integ.parse_config(yaml.safe_load(ROUTER_YAML))
    return FakeContext(ws, settings, integ, config, languages.get("pl"), home_data)
