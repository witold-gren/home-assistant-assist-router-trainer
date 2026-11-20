"""The inputs straight from Home Assistant, through the Assist Router export command.

``assist_router/training/export`` (Assist Router 0.1.8+, administrators only, read-only) hands
over router.yaml, the log of unrecognized commands, the test files, the automations with a
`conversation` trigger (also those from packages) and custom_sentences. The home's voice commands
(the speech-to-text WAV files of ``assist_pipeline: debug_recording_dir``, Assist Router 0.1.11+)
come with ``fetch_recordings`` into ``inputs/recordings`` - only the new ones. They are written to
the same files of workspace/inputs that the generators have always read, so nothing else
changes; ``inputs/ha_export.json`` keeps what came (the router's version for the panel).
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
from pathlib import Path
import shutil
import time
from typing import Any

import yaml

from .config import Workspace, load_settings, mark_token_rejected, token_rejected
from .ha_client import Connection, HaError, TokenRejected, load_connection

COMMAND = "assist_router/training/export"
RECORDINGS = "assist_router/training/recordings"
RECORDING_FILES = "assist_router/training/recording_files"
# the Assist Router version that brought each command
NEEDED = {COMMAND: "0.1.8", RECORDINGS: "0.1.11", RECORDING_FILES: "0.1.11"}
PATHS_PER_CALL = 200
EXPORT_FILE = "ha_export.json"  # in inputs/: version, language, when, how much came
TIMEOUT = 60


class OldRouter(HaError):
    """Assist Router in Home Assistant does not know a command yet."""


def websocket_url(url: str) -> str:
    """http://host:8123 -> ws://host:8123/api/websocket (https -> wss)."""
    url = url.rstrip("/")
    scheme, rest = url.split("://", 1) if "://" in url else ("http", url)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/api/websocket"


async def _session(connection: Connection, work):
    """One authenticated WebSocket; ``work(call)`` sends commands, ``call`` returns the result."""
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.ws_connect(websocket_url(connection.url), max_msg_size=0) as socket,
    ):
        await socket.receive_json()  # auth_required
        await socket.send_json({"type": "auth", "access_token": connection.token})
        auth = await socket.receive_json()
        if auth.get("type") != "auth_ok":
            raise TokenRejected(
                "Home Assistant 401: the token is wrong or expired - make a new long-lived token"
            )
        number = 0

        async def call(message: dict[str, Any]) -> Any:
            nonlocal number
            number += 1
            await socket.send_json({"id": number, **message})
            answer = await socket.receive_json()
            if answer.get("success"):
                return answer["result"]
            raise _refused(answer.get("error") or {}, message["type"])

        return await work(call)


def _refused(error: dict[str, Any], command: str) -> HaError:
    if error.get("code") == "unknown_command":
        return OldRouter(
            "Assist Router in Home Assistant is too old for the trainer - update it to "
            f"{NEEDED.get(command, '0.1.8')} or newer (it adds {command})"
        )
    if error.get("code") == "unauthorized":
        return HaError(
            "Home Assistant refused the export: the token's user must be an administrator"
        )
    return HaError(f"Home Assistant: {error.get('message') or error.get('code') or 'refused'}")


async def _export(connection: Connection) -> dict[str, Any]:
    return await _session(connection, lambda call: call({"type": COMMAND}))


def _run(ws: Workspace, work) -> Any:
    """``work(connection)`` for the saved connection (a rejected token is never sent again)."""
    if token_rejected(ws):
        raise TokenRejected("Home Assistant rejected the token - connect Home Assistant anew")
    connection = load_connection(ws)
    if not connection.ready:
        raise HaError("no Home Assistant connection - connect Home Assistant first")
    try:
        return asyncio.run(work(connection))
    except TokenRejected:
        mark_token_rejected(ws)
        raise
    except (TimeoutError, OSError) as err:
        raise HaError(f"Home Assistant at {connection.url} cannot be reached: {err}") from None
    except Exception as err:  # aiohttp errors (handshake, closed socket)
        if isinstance(err, HaError):
            raise
        raise HaError(f"Home Assistant at {connection.url}: {type(err).__name__}: {err}") from None


def export(ws: Workspace) -> dict[str, Any]:
    """The export answer for the saved connection."""
    return _run(ws, _export)


def log_csv(rows: list[dict[str, str]]) -> str:
    """The log as Assist Router writes it: UTF-8 with BOM, separator ";"."""
    if not rows:
        return ""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "﻿" + out.getvalue()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def save(ws: Workspace, data: dict[str, Any]) -> dict[str, Any]:
    """Write the export into workspace/inputs; files HA no longer has are removed."""
    inputs = load_settings(ws)["inputs"]
    written = {}

    def put(name: str, text: str) -> None:
        path = ws.path(inputs[name])
        if text:
            _write(path, text)
            written[name] = path.name
        elif path.exists():
            path.unlink()

    put("router", data.get("router_yaml") or "")
    tests = data.get("tests") or {}
    put("tests", tests.get("model_test.yaml", ""))
    put("test_data", tests.get("model_test_data.yaml", ""))
    put("log", log_csv(data.get("log") or []))
    config = ws.path(inputs["ha_config"])
    if config.exists() and config.resolve().is_relative_to(ws.root):
        shutil.rmtree(config)  # packages/ of the old share copy would add stale triggers
    automations = data.get("automations") or []
    _write(config / "automations.yaml", yaml.safe_dump(automations, allow_unicode=True))
    for item in data.get("custom_sentences") or []:
        name = Path(str(item.get("name", ""))).name
        language = Path(str(item.get("language", ""))).name
        if name.endswith(".yaml") and language:
            _write(config / "custom_sentences" / language / name, str(item.get("text", "")))
    summary = {
        "version": data.get("version"),
        "language": data.get("language"),
        "fetched": time.time(),
        "files": written,
        "log_rows": len(data.get("log") or []),
        "automations": len(automations),
        "custom_sentences": len(data.get("custom_sentences") or []),
    }
    _write(ws.root / "inputs" / EXPORT_FILE, json.dumps(summary, indent=2) + "\n")
    return summary


def fetch(ws: Workspace) -> dict[str, Any]:
    """Export from Home Assistant and save it - the panel's "Fetch from HA"."""
    return save(ws, export(ws))


def last(ws: Workspace) -> dict[str, Any] | None:
    """What the last fetch brought (None before the first one)."""
    path = ws.root / "inputs" / EXPORT_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- the home's voice commands -------------------------------------------------------------------


def recordings_folder(ws: Workspace) -> Path:
    return ws.root / "inputs" / "recordings"


async def _recordings(connection: Connection, folder: Path) -> dict[str, Any]:
    async def work(call) -> dict[str, Any]:
        listed = await call({"type": RECORDINGS})
        files = listed.get("files") or []
        missing = []
        for item in files:
            path = _inside(folder, item["path"])
            if path is not None and not (path.is_file() and path.stat().st_size == item["size"]):
                missing.append(item["path"])
        fetched = 0
        while missing:
            answer = await call({"type": RECORDING_FILES, "paths": missing[:PATHS_PER_CALL]})
            served = answer.get("files") or []
            if not served:
                break  # nothing more comes (files removed meanwhile)
            for item in served:
                path = _inside(folder, item["path"])
                if path is None:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(item["data"]))
                fetched += 1
            done = {item["path"] for item in served}
            missing = [p for p in missing if p not in done]
            print(f"recordings: {fetched} fetched", flush=True)
        return {
            "configured": bool(listed.get("configured")),
            "in_home_assistant": len(files),
            "fetched": fetched,
            "missing": len(missing),
        }

    return await _session(connection, work)


def _inside(folder: Path, relative: str) -> Path | None:
    """The local path of a recording, None for anything that would leave the folder."""
    path = (folder / relative).resolve()
    base = folder.resolve()
    return path if path.suffix == ".wav" and path.is_relative_to(base) else None


def fetch_recordings(ws: Workspace) -> dict[str, Any]:
    """New voice command recordings from Home Assistant into inputs/recordings (the ones already
    here are not sent again). An Assist Router older than 0.1.11 is said, not an error."""
    folder = recordings_folder(ws)
    try:
        return _run(ws, lambda connection: _recordings(connection, folder))
    except OldRouter as err:
        return {"configured": None, "fetched": 0, "error": str(err)}


def fetch_all(ws: Workspace) -> dict[str, Any]:
    """The export and, when the router data uses them (``generate.router.recordings``), the new
    voice command recordings - what "Fetch from HA", ``router-trainer fetch`` and the automatic
    training get."""
    summary = fetch(ws)
    if load_settings(ws)["generate"]["router"].get("recordings"):
        try:
            summary["recordings"] = fetch_recordings(ws)
        except (HaError, OSError, ValueError) as err:  # the rest came - recordings are extra
            summary["recordings"] = {"fetched": 0, "error": str(err)}
    return summary
