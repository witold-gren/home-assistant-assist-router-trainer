"""HTTP server of the trainer studio: the training panel as an editor, run on the GPU machine itself.

Everything the training panel does (``router_trainer.ui.server.Panel``: the inputs from Home Assistant,
the test, the dataset, training, export, validation, the machine's power) is reused; the studio adds the
login, the draft and history of trainer.yaml, switching the machine off after a job (a countdown that
can be cancelled) and one endpoint ``POST /api/call {"type": …}`` that the editor calls the way the Home
Dashboard and Assist Router editors call Home Assistant (``hass.callWS``) - like the wake word studio.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

from .. import ha_client, settings_store
from ..config import Workspace, init_workspace
from ..jobs import JobManager
from ..ui.server import CONTENT_TYPES, DOCS, Panel
from . import help as help_texts
from .auth import COOKIE, ENV, Auth, LoginRefused, parse_credentials

VERSION = "0.2.1"
WWW = Path(__file__).parent / "www"
POWER_OFF_DELAY = (
    120  # seconds between the end of a job and switching the machine off (can be cancelled)
)
MAX_BODY = 2_000_000
CONFIG_FOLDER = Path(
    os.environ.get("ROUTER_TRAINER_CONFIG") or Path.home() / ".config" / "router-trainer"
)  # the login secret (docker/config in the container)
CONTENT_TYPES = {
    **CONTENT_TYPES,
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".md": "text/markdown; charset=utf-8",
}


# the path of the guide's site_url (mkdocs.yml); its absolute links start with it
SITE_PREFIX = "/home-assistant-assist-router-trainer/"


class Studio:
    """The panel's state for the editor: jobs always here, in this machine's container."""

    def __init__(self, ws: Workspace, clock: Callable[[], float] = time.time) -> None:
        self.ws = ws
        self.panel = Panel(ws)
        self.clock = clock
        # at: when the machine goes off (cancellable)
        self.power_off: dict = {"after_training": False, "at": None}
        self.power_off_error: str | None = None
        self._was_running = False

    # --- switching the machine off after a job -------------------------------------------------------
    def set_power_off(self, after_training: bool | None = None, cancel: bool = False) -> dict:
        if after_training is not None:
            if after_training and self.panel._power_ready() is None:
                raise ValueError("set the machine's switch and power sensor first (Power)")
            self.power_off["after_training"] = bool(after_training)
            if not after_training:
                self.power_off["at"] = None
        if cancel:
            self.power_off = {"after_training": False, "at": None}
        return dict(self.power_off)

    def tick(self) -> None:
        """Called with every state: arms the countdown when a job ends (not after Stop), switches
        the machine off when it runs out and nothing runs any more."""
        job = (self.panel.status or {}).get("job") or {}
        running = bool(job.get("running"))
        ended = self._was_running and not running
        if ended and self.power_off["after_training"] and job.get("state") != "stopped":
            self.power_off["at"] = self.clock() + POWER_OFF_DELAY
        self._was_running = running
        at = self.power_off["at"]
        if at is None or self.clock() < at or running:
            return  # an evaluation after the training: wait for it
        self.power_off = {"after_training": False, "at": None}
        try:
            self.panel.switch_machine(False)
            self.power_off_error = None
        except (ValueError, RuntimeError) as err:
            self.power_off_error = str(err)

    # --- one call of the editor ------------------------------------------------------------------------
    def call(self, message: dict, user: str = "") -> object:
        kind = message.get("type")
        arg = lambda name, default="": message.get(name, default)  # noqa: E731
        if kind == "state":
            state = self.panel.state(arg("language") or None)
            self.tick()
            state["help"] = help_texts.texts(state["language"])
            state["studio"] = {
                "user": user,
                "version": VERSION,
                "power_off": dict(self.power_off),
                "power_off_delay": POWER_OFF_DELAY,
                "power_off_error": self.power_off_error,
                "in_container": bool(os.environ.get("ROUTER_TRAINER_IN_CONTAINER")),
            }
            return state
        if kind == "settings/get":
            return settings_store.load(self.ws)
        if kind == "draft/save":
            return settings_store.save_draft(self.ws, str(arg("text")), str(arg("base")))
        if kind == "draft/discard":
            settings_store.discard(self.ws)
            return {"ok": True}
        if kind == "settings/save":
            return settings_store.save(
                self.ws,
                str(arg("text")),
                str(arg("base")),
                str(arg("note")),
                bool(arg("force", False)),
                user,
            )
        if kind == "history/list":
            return {"versions": settings_store.versions(self.ws)}
        if kind == "history/get":
            return {"text": settings_store.history_get(self.ws, str(arg("id")))["text"]}
        if kind == "history/restore":
            return settings_store.restore(self.ws, str(arg("id")))
        if kind == "action":
            return {"ok": True, "result": self.panel.action(dict(message))}
        if kind == "power/off_after_training":
            return self.set_power_off(after_training=bool(arg("enabled", False)))
        if kind == "power/cancel":
            return self.set_power_off(cancel=True)
        if kind == "ha_entities":
            return self.panel.ha_entities()
        if kind == "jobs/history":
            return {"jobs": JobManager(self.ws.root).history()}
        if kind == "jobs/log":
            return {"text": JobManager(self.ws.root).log_text(str(arg("log")))}
        raise ValueError(f"unknown call '{kind}'")


ERRORS = (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, ha_client.HaError)


def _handler(studio: Studio, auth: Auth):
    class Handler(BaseHTTPRequestHandler):
        server_version = "router-trainer-studio"

        def log_message(self, format, *args):
            if getattr(self.server, "verbose", True) and not self.path.startswith(
                ("/api/call", "/api/health")
            ):
                super().log_message(format, *args)

        def _send(
            self, status: HTTPStatus, body: bytes, content_type: str, headers: dict | None = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):  # the page was reloaded meanwhile
                self.close_connection = True

        def _json(self, data, status: HTTPStatus = HTTPStatus.OK, headers: dict | None = None):
            body = json.dumps(data, ensure_ascii=False).encode()
            self._send(status, body, "application/json; charset=utf-8", headers)

        def _user(self) -> str | None:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return auth.check(cookie[COOKIE].value if COOKIE in cookie else None)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                raise ValueError("request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("bad request")
            return data

        def _static(self, name: str, folder: Path = WWW) -> None:
            file = (folder / name).resolve()
            if folder.resolve() not in file.parents or not file.is_file():
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            content_type = CONTENT_TYPES.get(file.suffix, "application/octet-stream")
            self._send(HTTPStatus.OK, file.read_bytes(), content_type)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/health":
                return self._json({"ok": True, "version": VERSION})
            if url.path == "/login":
                return self._static("login.html")
            if url.path == "/favicon.svg":
                return self._static("favicon.svg")
            if self._user() is None:
                if url.path.startswith(("/api/", "/docs/")):
                    return self._json(
                        {"error": "log in first", "login": True}, HTTPStatus.UNAUTHORIZED
                    )
                return self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {"Location": "/login"})
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path.removeprefix("/static/"))
            if url.path.startswith(SITE_PREFIX):
                # the guide's own links (MkDocs site_url, e.g. the language switch) point at its public
                # address: here it lives at /docs/
                rest = url.path.removeprefix(SITE_PREFIX)
                return self._send(
                    HTTPStatus.FOUND, b"", "text/plain", {"Location": "/docs/" + rest}
                )
            if url.path.startswith("/docs/"):
                # MkDocs (i18n suffix): English at the top of site/, Polish in site/pl/; the "?" opens
                # /docs/<language>/, so /docs/en/... is the top
                name = url.path.removeprefix("/docs/")
                name = "" if name == "en" else name.removeprefix("en/")
                if name and "." not in name.rsplit("/", 1)[-1] and not name.endswith("/"):
                    name += "/"  # a page's folder without its slash
                return self._static(
                    name + "index.html" if name.endswith("/") or not name else name, DOCS
                )
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                data = self._body()
            except (ValueError, json.JSONDecodeError) as err:
                return self._json({"error": str(err) or "bad JSON"}, HTTPStatus.BAD_REQUEST)
            if path == "/api/login":
                try:
                    cookie = auth.login(
                        self.client_address[0],
                        str(data.get("user", "")),
                        str(data.get("password", "")),
                    )
                except LoginRefused as err:
                    return self._json(
                        {"error": str(err), "retry_after": err.retry_after},
                        HTTPStatus.UNAUTHORIZED,
                    )
                secure = self.headers.get("X-Forwarded-Proto") == "https"
                return self._json(
                    {"ok": True}, headers={"Set-Cookie": auth.set_cookie(cookie, secure)}
                )
            if path == "/api/logout":
                return self._json({"ok": True}, headers={"Set-Cookie": auth.clear_cookie()})
            user = self._user()
            if user is None:
                return self._json({"error": "log in first", "login": True}, HTTPStatus.UNAUTHORIZED)
            if path != "/api/call":
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            try:
                return self._json(studio.call(data, user))
            except settings_store.Conflict as err:
                return self._json({"error": str(err), "conflict": True}, HTTPStatus.CONFLICT)
            except ERRORS as err:
                return self._json({"error": str(err)}, HTTPStatus.BAD_REQUEST)

    return Handler


def make_server(
    ws: Workspace,
    credentials: tuple[str, str],
    host: str = "127.0.0.1",
    port: int = 8790,
    verbose: bool = True,
    secret_folder: Path | None = None,
    **studio_options,
) -> ThreadingHTTPServer:
    studio = Studio(ws, **studio_options)
    auth = Auth(credentials, secret_folder or CONFIG_FOLDER)
    server = ThreadingHTTPServer((host, port), _handler(studio, auth))
    server.verbose = verbose
    server.studio = studio
    server.auth = auth
    return server


def serve(root: Path, host: str, port: int) -> None:
    try:
        credentials = parse_credentials(os.environ.get(ENV))
    except ValueError as err:
        raise SystemExit(f"error: {err}") from None
    server = make_server(init_workspace(root), credentials, host, port)
    print(
        f"Assist Router trainer studio on http://{host}:{port}/ "
        f"(user '{credentials[0]}', password in {ENV})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
