"""The GPU machine switched on and off through Home Assistant, and the panel's HA client."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import pytest

from router_trainer import config, ha_client, power
from router_trainer.config import init_workspace


class FakeHa:
    """States and service calls of Home Assistant, as Client answers them."""

    def __init__(self, switch: str = "on", watts: str = "54.3") -> None:
        self.states = {"switch.maszyna_gpu": switch, "sensor.plug_power": watts}
        self.calls: list[str] = []

    def entity_state(self, entity_id, timeout=5):
        return {"state": self.states[entity_id], "attributes": {}}

    def call_service(self, domain, service, entity_id, timeout=10):
        self.calls.append(f"{domain}.{service} {entity_id}")


SETTINGS = power.PowerSettings(switch="switch.maszyna_gpu", sensor="sensor.plug_power", off_watts=5)


def connect(ws, monkeypatch, url: str = "http://homeassistant.local:8123") -> None:
    """The panel's "Connect to HA" with a made-up Home Assistant."""
    monkeypatch.setattr(config, "check_ha", lambda url, token: {"name": "Dom", "version": "x"})
    config.save_ha(ws, url, "t" * 40)


def test_settings_kept_next_to_the_connection(tmp_path, monkeypatch) -> None:
    ws = init_workspace(tmp_path / "ws")
    assert not power.load_power(ws).ready
    connect(ws, monkeypatch)
    power.save_power(
        ws, power.PowerSettings("switch.maszyna_gpu", "sensor.plug_power", off_watts="7")
    )
    assert power.load_power(ws) == power.PowerSettings(
        "switch.maszyna_gpu", "sensor.plug_power", 7.0
    )
    # the connection changed: the power settings stay, the token too
    config.save_ha(ws, "http://10.0.0.2:8123", None)
    assert power.load_power(ws).switch == "switch.maszyna_gpu"
    assert ha_client.load_connection(ws) == ha_client.Connection("http://10.0.0.2:8123", "t" * 40)
    assert ws.ha_file.stat().st_mode & 0o077 == 0
    assert "t" * 40 not in ws.ha_file.read_text()  # the token lives in its own file
    for bad, match in (
        (power.PowerSettings(switch="sensor.plug", sensor="sensor.x"), "switch"),
        (power.PowerSettings(switch="switch.plug", sensor="switch.x"), "sensor"),
        (power.PowerSettings(switch="switch.plug", sensor="sensor.x", off_watts=0), "threshold"),
        (power.PowerSettings(switch="switch.plug", sensor="sensor.x", off_watts="x"), "threshold"),
        (power.PowerSettings(switch="switch.Bad Name", sensor="sensor.x"), "switch"),
    ):
        with pytest.raises(ValueError, match=match):
            power.save_power(ws, bad)
    # an input_boolean is a switch too
    power.save_power(ws, power.PowerSettings("input_boolean.gpu", "sensor.plug_power"))
    assert power.load_power(ws).switch == "input_boolean.gpu"


def test_state_for_the_header() -> None:
    def state(ha, reachable=False):
        return power.machine_state(ha, SETTINGS, reachable)

    assert state(FakeHa(), reachable=True) == {"switch": "on", "watts": 54.3, "machine": "on"}
    assert state(FakeHa())["machine"] == "starting"  # on, the SSH port not answering yet
    assert state(FakeHa(switch="off", watts="48"))["machine"] == "stopping"  # HA shuts it down
    assert state(FakeHa(switch="off", watts="0.4"))["machine"] == "off"
    assert state(FakeHa(switch="unavailable", watts="unavailable")) == {
        "switch": "unavailable",
        "watts": None,
        "machine": "unknown",
    }


def test_switch_flipped_in_home_assistant() -> None:
    ha = FakeHa()
    power.switch_machine(ha, SETTINGS, on=False)
    power.switch_machine(ha, SETTINGS, on=True)
    assert ha.calls == ["switch.turn_off switch.maszyna_gpu", "switch.turn_on switch.maszyna_gpu"]


def test_home_assistant_states_and_services_over_http() -> None:
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self, body, status=200):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/api/states/switch.plug":
                self._answer({"entity_id": "switch.plug", "state": "on"})
            elif self.path == "/api/states/switch.nope":
                self._answer({"message": "Entity not found."}, 404)
            else:
                self._answer(
                    [{"entity_id": "sensor.p", "attributes": {"unit_of_measurement": "W"}}]
                )

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("POST", self.path, body))
            self._answer([])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        client = ha_client.Client(ha_client.Connection(url, "t" * 40))
        assert client.entity_state("switch.plug")["state"] == "on"
        assert client.entities()[0]["entity_id"] == "sensor.p"
        client.call_service("switch", "turn_off", "switch.plug")
        assert seen[0] == ("GET", "/api/states/switch.plug", "Bearer " + "t" * 40)
        assert seen[-1] == ("POST", "/api/services/switch/turn_off", {"entity_id": "switch.plug"})
        with pytest.raises(ha_client.HaError, match="404: Entity not found"):
            client.entity_state("switch.nope")
    finally:
        server.shutdown()
        server.server_close()
    with pytest.raises(ha_client.HaError, match="cannot be reached"):
        client.entity_state("switch.plug", timeout=1)
    with pytest.raises(ha_client.HaError, match="no Home Assistant connection"):
        ha_client.Client(ha_client.Connection("http://ha:8123", ""))


def test_home_assistant_name_looked_up_once_ipv4_first(monkeypatch) -> None:
    """macOS waits 5 s for an IPv6 answer of homeassistant.local on every request: asked once,
    IPv4 only."""
    asked = []

    def getaddrinfo(host, port, family=0, kind=0):
        asked.append((host, family))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(ha_client, "_resolved", {})
    url, headers = ha_client._direct_url("http://homeassistant.local:8123/api/states/switch.x")
    assert url == "http://192.168.1.10:8123/api/states/switch.x"
    assert headers == {"Host": "homeassistant.local:8123"}
    ha_client._direct_url("http://homeassistant.local:8123/api/states/sensor.y")
    assert asked == [("homeassistant.local", socket.AF_INET)]  # kept
    # https keeps the name (the certificate is for it); an address stays as it is
    assert ha_client._direct_url("https://ha.example.com/api") == ("https://ha.example.com/api", {})
    assert ha_client._direct_url("http://10.0.0.2:8123/api") == ("http://10.0.0.2:8123/api", {})


def test_home_assistant_name_not_found_leaves_the_url(monkeypatch) -> None:
    def fail(*args):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    monkeypatch.setattr(ha_client, "_resolved", {})
    assert ha_client._direct_url("http://nope.local:8123/api") == ("http://nope.local:8123/api", {})


def test_connect_check_uses_the_ipv4_address(monkeypatch) -> None:
    """ "Connect to HA" goes through the same lookup as every other request."""
    opened = {}

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"location_name": "Dom", "version": "2026.10.4"}'

    def urlopen(request, timeout):
        opened.update(url=request.full_url, host=request.get_header("Host"))
        return Answer()

    monkeypatch.setattr(ha_client, "_resolved", {})
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family=0, kind=0: [(socket.AF_INET, 1, 6, "", ("192.168.1.10", port))],
    )
    monkeypatch.setattr(config.urllib.request, "urlopen", urlopen)
    assert config.check_ha("http://homeassistant.local:8123", "t") == {
        "name": "Dom",
        "version": "2026.10.4",
    }
    assert opened == {
        "url": "http://192.168.1.10:8123/api/config",
        "host": "homeassistant.local:8123",
    }


def test_forbidden_says_what_to_check() -> None:
    """403 from HA: a banned address (ip_bans.yaml, e.g. behind a VPN) or a non-admin user."""
    assert "ip_bans.yaml" in ha_client.explain(403, "403: Forbidden")
    assert "administrator" in ha_client.explain(403, "")
    assert "401" in ha_client.explain(401, "") and "token" in ha_client.explain(401, "")


def test_rejected_token_sent_once_until_connected_anew(tmp_path, monkeypatch) -> None:
    """Every 401 is a failed login for Home Assistant's ip_ban: one, then nothing until "Connect"."""
    from router_trainer.context import Context

    good = "g" * 40
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            if self.headers.get("Authorization") != f"Bearer {good}":
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            body = (
                {"location_name": "Dom", "version": "x"}
                if self.path == "/api/config"
                else {"state": "on"}
            )
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        ws = init_workspace(tmp_path / "ws")
        config.save_ha(ws, url, good)
        (ws.root / config.TOKEN_FILE).write_text("b" * 40 + "\n")  # the token was revoked meanwhile
        assert not config.token_rejected(ws)
        connection = ha_client.load_connection(ws)
        with pytest.raises(ha_client.TokenRejected, match="401"):
            ha_client.Client(connection, ws).entity_state("switch.x")
        assert config.token_rejected(ws)
        asked = len(seen)
        with pytest.raises(ha_client.TokenRejected, match="not asked again"):
            ha_client.Client(connection, ws).entities()
        with pytest.raises(RuntimeError, match="not asked again"):  # the jobs (snapshot, tests)
            Context(ws, config.load_settings(ws), None, None, None).token()
        assert len(seen) == asked  # Home Assistant never asked
        with pytest.raises(
            ValueError, match="rejected the token"
        ):  # "Connect" with the saved token
            config.save_ha(ws, url, None)
        assert len(seen) == asked + 1 and config.token_rejected(ws)
        config.save_ha(ws, url, good)  # a good token: asked again
        assert not config.token_rejected(ws)
        assert (
            ha_client.Client(ha_client.load_connection(ws), ws).entity_state("switch.x")["state"]
            == "on"
        )
        # a client without the workspace (no saved connection) remembers nothing
        with pytest.raises(ha_client.TokenRejected):
            ha_client.Client(ha_client.Connection(url, "b" * 40)).entities()
        assert not config.token_rejected(ws)
    finally:
        server.shutdown()
        server.server_close()


def test_a_new_rejected_token_keeps_the_saved_connection_asked(tmp_path, monkeypatch) -> None:
    ws = init_workspace(tmp_path / "ws")
    connect(ws, monkeypatch)

    def refuse(url, token):
        raise ValueError("Home Assistant rejected the token")

    monkeypatch.setattr(config, "check_ha", refuse)
    with pytest.raises(ValueError):
        config.save_ha(ws, "http://homeassistant.local:8123", "n" * 40)  # a typo in a new token
    assert not config.token_rejected(ws)  # nothing saved, the saved token was not refused
