"""The tests' own guards (gpu-studio.md section 9): nothing leaves 127.0.0.1 and no test can switch a real
machine off."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
from urllib import error, request

import aiohttp
import pytest

from router_trainer import ha_client, power


def test_requests_to_other_computers_are_blocked() -> None:
    with pytest.raises(error.URLError, match="never leave this computer"):
        request.urlopen("http://homeassistant.local:8123/api/", timeout=2)
    with pytest.raises(OSError, match="never leave this computer"):
        socket.create_connection(("192.0.2.10", 8123), timeout=2)

    async def websocket() -> None:
        async with aiohttp.ClientSession() as session:
            await session.ws_connect("ws://homeassistant.local:8123/api/websocket")

    with pytest.raises(aiohttp.ClientError):
        asyncio.run(websocket())


def test_this_computer_still_answers() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        for host in ("127.0.0.1", "localhost"):
            with request.urlopen(f"http://{host}:{port}/", timeout=2) as answer:
                assert answer.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()


def test_switching_the_machine_off_is_only_written_down(harmless_power_off) -> None:
    client = ha_client.Client(ha_client.Connection("http://homeassistant.local:8123", "t" * 40))
    settings = power.PowerSettings(switch="switch.maszyna_gpu", sensor="sensor.maszyna_gpu_power")
    power.switch_machine(client, settings, on=False)
    assert harmless_power_off == ["switch.turn_off switch.maszyna_gpu"]
