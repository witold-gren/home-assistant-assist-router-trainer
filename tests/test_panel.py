"""The training panel's logic (served by the studio): jobs it starts, the log, the test actions, the
inputs from Home Assistant, the router code, the machine's power and the texts."""

from __future__ import annotations

import threading

import pytest

from router_trainer import ha_inputs, router_source
from router_trainer.config import init_workspace
from router_trainer.ui import server as server_module
from router_trainer.ui.backend import CHECK_SCRIPT, LocalBackend
from router_trainer.ui.texts import TEXTS


def test_save_ha_checks_and_keeps_the_token_private(tmp_path, monkeypatch) -> None:
    from router_trainer import config

    ws = init_workspace(tmp_path / "ws")
    monkeypatch.setattr(
        config, "check_ha", lambda url, token: {"name": "Dom", "version": "2026.10"}
    )
    with pytest.raises(ValueError, match="token"):
        config.save_ha(ws, "http://ha:8123", None)
    saved = config.save_ha(ws, "http://ha:8123/", "abc")
    assert saved["url"] == "http://ha:8123" and saved["checked"]["name"] == "Dom"
    token = ws.root / "ha_token"
    assert token.read_text().strip() == "abc" and oct(token.stat().st_mode)[-3:] == "600"
    settings = config.load_settings(ws)
    assert config.token_path(ws, settings) == token
    # a new address without a token keeps the saved token
    assert config.save_ha(ws, "http://ha2:8123", "")["url"] == "http://ha2:8123"
    assert token.read_text().strip() == "abc"


class FakeBackend:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.log = ""

    def status(self, offset: int) -> dict:
        return {"job": {"log": "a.log", "running": True, "title": "t", "state": "running"},
                "log": self.log[offset:], "log_offset": len(self.log), "runs": [], "models": ["e4b"]}  # fmt: skip

    def start(self, kind, title, args) -> None:
        self.started.append((kind, title, args))

    def stop(self) -> None:
        self.started.append(("stop",))

    def cli_json(self, *args):
        self.started.append(("cli", *args))
        return []

    def check_command(self) -> list[str]:
        return ["true"]


@pytest.fixture
def panel(tmp_path):
    fake = FakeBackend()
    panel = server_module.Panel(init_workspace(tmp_path / "ws"))
    panel._backend = fake
    panel.fake = fake
    return panel


def test_panel_builds_job_commands(panel) -> None:
    panel.start({"kind": "data", "dataset": "oct27", "steps": ["build", "router", "nope"]})
    kind, _, args = panel.fake.started[-1]
    assert kind == "data" and args == [
        "pipeline",
        "--steps",
        "router",
        "build",
        "--dataset",
        "oct27",
    ]
    panel.start({"kind": "train", "dataset": "oct27", "models": ["e4b", "e2b"], "resume": True,
                 "set": {"epochs": 2, "learning_rate": "", "evil": 1}})  # fmt: skip
    _, _, args = panel.fake.started[-1]
    assert args[:4] == ["pipeline", "--steps", "train", "export"]
    assert "--resume" in args and args[-2:] == ["--set", "epochs=2"]
    panel.start({"kind": "train", "dataset": "oct27", "models": ["e2b"], "then_export": False})
    assert panel.fake.started[-1][2][:4] == ["pipeline", "--steps", "train", "--dataset"]
    panel.start({"kind": "export", "run": "oct27-e4b"})
    assert panel.fake.started[-1][2] == ["export", "--run", "oct27-e4b"]
    panel.stop()
    assert panel.fake.started[-1] == ("stop",)
    for bad in ({"kind": "data", "dataset": "../x", "steps": ["build"]},
                {"kind": "train", "dataset": "a", "models": []}, {"kind": "rm"}):  # fmt: skip
        with pytest.raises(ValueError):
            panel.start(bad)


def test_panel_reads_the_log_incrementally(panel) -> None:
    panel.fake.log = '==> train x\n@@metric {"step": 5, "loss": 1.0}\n'
    panel.poll(force=True)
    state = panel.state("pl")
    assert state["language"] == "pl" and state["progress"]["stage"] == "train x"
    assert state["progress"]["metrics"][0]["step"] == 5 and "@@" not in state["log"]
    panel.fake.log += '@@metric {"step": 10, "loss": 0.8}\n'
    panel.poll(force=True)
    assert [m["step"] for m in panel.state()["progress"]["metrics"]] == [5, 10]


def test_panel_test_actions(panel) -> None:
    panel.action({"action": "testgen", "name": "auto1"})
    assert panel.fake.started[-1] == ("testgen", "test auto1", ["testgen", "--name", "auto1"])
    panel.action({"action": "active_test", "name": "ha"})
    assert panel.fake.started[-1] == ("cli", "tests", "--active", "ha")
    panel.action({"action": "review", "name": "auto1", "case": "router:x", "rejected": True})
    assert panel.fake.started[-1] == (
        "cli",
        "review",
        "--name",
        "auto1",
        "--case",
        "router:x",
        "--reject",
    )
    panel.action({"action": "review", "name": "auto1", "case": "router:x", "rejected": False})
    assert panel.fake.started[-1][-1] == "--keep"
    with pytest.raises(ValueError):
        panel.action({"action": "active_test", "name": "../x"})
    with pytest.raises(ValueError, match="unknown action"):
        panel.action({"action": "send"})  # the old Mac → SSH step is gone


def wait(condition, seconds: float = 5.0) -> bool:
    import time

    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_fetch_from_home_assistant_runs_in_the_background(panel, monkeypatch) -> None:
    release = threading.Event()

    def fetch(ws):
        release.wait(5)
        return {"version": "0.1.8"}

    monkeypatch.setattr(ha_inputs, "fetch", fetch)
    panel.action({"action": "fetch"})
    assert panel.state()["fetching"]["running"]
    with pytest.raises(RuntimeError, match="still running"):
        panel.action({"action": "fetch"})
    release.set()
    assert wait(lambda: not panel.fetching["running"])
    assert panel.fetching == {"running": False, "ok": True, "summary": {"version": "0.1.8"}}

    def refused(ws):
        raise ha_inputs.HaError("Assist Router in Home Assistant is too old")

    monkeypatch.setattr(ha_inputs, "fetch", refused)
    panel.action({"action": "fetch"})
    assert wait(lambda: not panel.fetching["running"])
    assert panel.fetching["ok"] is False and "too old" in panel.fetching["error"]


def test_router_code_follows_home_assistant(panel, monkeypatch) -> None:
    with pytest.raises(ValueError, match="fetch from Home Assistant first"):
        panel.action({"action": "router_fetch"})
    (panel.ws.root / "inputs").mkdir(parents=True, exist_ok=True)
    (panel.ws.root / "inputs" / ha_inputs.EXPORT_FILE).write_text('{"version": "0.1.8"}')
    fetched = []
    monkeypatch.setattr(router_source, "fetch", lambda root, version: fetched.append(version))
    monkeypatch.setattr(panel, "poll", lambda force=False: {"running": True})
    with pytest.raises(RuntimeError, match="job is running"):
        panel.action({"action": "router_fetch"})
    monkeypatch.setattr(panel, "poll", lambda force=False: {"running": False})
    panel.action({"action": "router_fetch"})
    assert fetched == ["0.1.8"]
    assert panel.router_state()["ha_version"] == "0.1.8"


def test_machine_check_runs_inside_the_container(panel) -> None:
    command = LocalBackend(panel.ws).check_command()
    assert command[:2] == ["bash", "-c"] and "nvidia-smi" in CHECK_SCRIPT
    assert "ssh" not in CHECK_SCRIPT and "rsync" not in CHECK_SCRIPT
    panel.action({"action": "check"})
    assert wait(lambda: not panel.task.running)
    assert panel.task.code == 0


def test_machine_power_through_home_assistant(panel, monkeypatch) -> None:
    from router_trainer import ha_client, power

    from .test_power import FakeHa, connect

    assert panel.machine() is None and panel.state()["machine"] is None  # not set up: no button
    connect(panel.ws, monkeypatch)
    fake = FakeHa()
    monkeypatch.setattr(ha_client, "Client", lambda *args: fake)
    fake.entities = lambda timeout=10: [
        {"entity_id": "switch.maszyna_gpu", "attributes": {"friendly_name": "Maszyna GPU"}},
        {"entity_id": "sensor.plug_power", "attributes": {"unit_of_measurement": "W"}},
        {"entity_id": "sensor.temperature", "attributes": {"unit_of_measurement": "°C"}},
    ]
    entities = panel.ha_entities()
    assert [e["id"] for e in entities["sensors"]] == ["sensor.plug_power"]  # only power (W)
    assert entities["switches"] == [{"id": "switch.maszyna_gpu", "name": "Maszyna GPU"}]
    with pytest.raises(ValueError, match="switch and power sensor first"):
        panel.action({"action": "machine_on"})
    panel.action(
        {"action": "power_settings", "switch": "switch.maszyna_gpu", "sensor": "sensor.plug_power"}
    )
    assert power.load_power(panel.ws).ready and power.load_power(panel.ws).off_watts == 5.0
    assert panel.state()["ha"]["power"]["switch"] == "switch.maszyna_gpu"
    # the panel runs on the machine: a switch that is on is a machine that is on
    assert panel.machine() == {"switch": "on", "watts": 54.3, "machine": "on"}
    assert panel.machine_cached()["machine"] == "on"

    monkeypatch.setattr(panel, "poll", lambda force=False: {"running": True})
    with pytest.raises(RuntimeError, match="training job is running"):  # never cut a training
        panel.action({"action": "machine_off"})
    monkeypatch.setattr(panel, "poll", lambda force=False: {"running": False})
    panel.action({"action": "machine_off"})
    assert fake.calls == ["switch.turn_off switch.maszyna_gpu"]

    # Home Assistant not answering: "no reading", the reason in the tooltip
    def unreachable(*args, **kwargs):
        raise ha_client.HaError("Home Assistant at http://ha cannot be reached: timed out")

    fake.entity_state = unreachable
    fake.call_service = unreachable
    panel._machine_cache = None
    answer = panel.machine()
    assert answer["machine"] == "unknown" and "cannot be reached" in answer["error"]
    with pytest.raises(RuntimeError, match="cannot be reached"):
        panel.action({"action": "machine_off"})


def test_page_answered_at_once_while_the_state_is_read(panel, monkeypatch) -> None:
    """The state is read in the background: the page never waits for it."""
    import time

    release = threading.Event()

    def slow_status(offset):
        release.wait(5)
        raise OSError("timed out")

    monkeypatch.setattr(panel.fake, "status", slow_status)
    started = time.time()
    state = panel.state("pl")
    assert time.time() - started < 1 and state["checking"]
    release.set()
    assert wait(lambda: not panel.state()["checking"])
    assert "timed out" in panel.state()["error"]


def test_rejected_token_shown_and_never_asked_until_connected(panel, monkeypatch) -> None:
    """After a 401 nothing asks Home Assistant; "Connect to HA" clears it."""
    from router_trainer import config, ha_client, power

    from .test_power import connect

    connect(panel.ws, monkeypatch)
    power.save_power(panel.ws, power.PowerSettings("switch.maszyna_gpu", "sensor.plug_power"))
    config.mark_token_rejected(panel.ws)
    asked = []
    monkeypatch.setattr(
        power, "machine_state", lambda *args: asked.append(args) or {"machine": "on"}
    )
    for _ in range(3):
        assert panel.machine()["machine"] == "rejected"
        assert panel.machine_cached()["machine"] == "rejected"
    assert panel.state()["ha"]["rejected"] is True and asked == []
    with pytest.raises(ha_client.TokenRejected):
        panel.ha_entities()
    with pytest.raises(RuntimeError, match="not asked again"):
        panel.action({"action": "machine_on"})
    connect(panel.ws, monkeypatch)  # "Connect to HA": checked again and saved
    assert panel.state()["ha"]["rejected"] is False
    assert panel.machine() == {"machine": "on"} and len(asked) == 1


def test_every_language_has_every_text() -> None:
    keys = set(TEXTS["en"])
    for language, texts in TEXTS.items():
        assert set(texts) == keys, language
