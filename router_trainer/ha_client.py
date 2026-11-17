"""A small Home Assistant REST client for the panel: states, the entity list and services.

The connection is the one saved by the panel (workspace/home_assistant.json + the token file).
The token is never printed nor sent to the page.

``_direct_url``: macOS asks mDNS for IPv4 and IPv6 at once and waits 5 s for an IPv6 answer for
``homeassistant.local`` that never comes - on every request. The name is looked up once (IPv4
first), kept a few minutes, and the request goes to the address with the original ``Host``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
from urllib import error, parse, request

from .config import (
    REJECTED_MESSAGE,
    Workspace,
    load_settings,
    mark_token_rejected,
    token_path,
    token_rejected,
)

DNS_CACHE_SECONDS = 300
TIMEOUT = 10

_resolved: dict[tuple[str, int], tuple[float, str]] = {}  # (host, port) -> (time, IPv4 address)


class HaError(RuntimeError):
    """Home Assistant cannot be reached or refused the request."""


class TokenRejected(HaError):
    """Home Assistant answered 401 - remembered, so the token is not sent again (ip_ban)."""


def _direct_url(url: str) -> tuple[str, dict[str, str]]:
    """``http://homeassistant.local:8123/...`` -> the same URL with the IPv4 address, plus its
    Host header. HTTPS keeps the name (the certificate is for it); an address or a failed lookup
    leaves the URL as it is."""
    import ipaddress
    import socket

    parts = parse.urlsplit(url)
    host, port = parts.hostname or "", parts.port or 80
    if parts.scheme != "http" or not host:
        return url, {}
    try:
        ipaddress.ip_address(host)
        return url, {}
    except ValueError:
        pass
    cached = _resolved.get((host, port))
    if cached and time.time() - cached[0] < DNS_CACHE_SECONDS:
        address = cached[1]
    else:
        try:
            address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        except OSError:
            return url, {}
        _resolved[(host, port)] = (time.time(), address)
    netloc = f"{address}:{parts.port}" if parts.port else address
    return parse.urlunsplit(parts._replace(netloc=netloc)), {"Host": parts.netloc}


def explain(status: int, body: str) -> str:
    try:
        message = json.loads(body).get("message", "")
    except (ValueError, AttributeError):
        message = body.strip()[:200]
    if status == 401:
        return "Home Assistant 401: the token is wrong or expired - make a new long-lived token"
    if status == 403:
        return (
            "Home Assistant 403: refused - this computer's address may be banned "
            "(ip_bans.yaml in the HA config) or the token's user is not an administrator"
        )
    if status == 404:
        return f"Home Assistant 404: {message or 'entity or service not found'}"
    return f"Home Assistant {status}: {message or 'refused'}"


@dataclass
class Connection:
    url: str = ""
    token: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.url and self.token)


def load_connection(ws: Workspace) -> Connection:
    """The address and token saved by the panel (an empty Connection when not set up)."""
    settings = load_settings(ws)
    path = token_path(ws, settings)
    try:
        token = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        token = ""
    return Connection(str(settings["home_assistant"].get("url") or "").rstrip("/"), token)


class Client:
    def __init__(self, connection: Connection, ws: Workspace | None = None) -> None:
        """``ws``: the workspace whose saved connection this is - a token Home Assistant rejected
        there is not sent again until it is connected anew (each 401 counts for ip_ban)."""
        if not connection.ready:
            raise HaError(
                "no Home Assistant connection - connect Home Assistant in the panel (step 1)"
            )
        if ws is not None and token_rejected(ws):
            raise TokenRejected(REJECTED_MESSAGE)
        self.connection = connection
        self.ws = ws

    def _open(
        self,
        path: str,
        data: bytes | None = None,
        method: str = "GET",
        api: str = "/api",
        timeout: float = TIMEOUT,
    ):
        url, host = _direct_url(f"{self.connection.url}{api}{path}")
        headers = {
            "Authorization": f"Bearer {self.connection.token}",
            "Content-Type": "application/json",
            **host,
        }
        try:
            return request.urlopen(
                request.Request(url, data=data, method=method, headers=headers), timeout=timeout
            )
        except error.HTTPError as err:
            if err.code == 401:  # a failed login for ip_ban: never sent again with this token
                if self.ws is not None:
                    mark_token_rejected(self.ws)
                raise TokenRejected(explain(401, "")) from None
            raise HaError(explain(err.code, err.read().decode("utf-8", "replace"))) from None
        except (error.URLError, OSError) as err:
            reason = getattr(err, "reason", err)
            raise HaError(
                f"Home Assistant at {self.connection.url} cannot be reached: {reason}"
            ) from None

    def entity_state(self, entity_id: str, timeout: float = 5) -> dict[str, Any]:
        """{"state", "attributes", ...} of an entity."""
        with self._open(f"/states/{parse.quote(entity_id)}", timeout=timeout) as response:
            return json.load(response)

    def entities(self, timeout: float = 10) -> list[dict[str, Any]]:
        with self._open("/states", timeout=timeout) as response:
            return json.load(response)

    def call_service(self, domain: str, service: str, entity_id: str, timeout: float = 10) -> None:
        body = json.dumps({"entity_id": entity_id}).encode()
        with self._open(
            f"/services/{parse.quote(domain)}/{parse.quote(service)}",
            data=body,
            method="POST",
            timeout=timeout,
        ):
            pass
