"""The inputs from Home Assistant (export command), the router code of HA's version and
trainer.yaml edited from the panel."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
import threading

import pytest
import yaml

from router_trainer import ha_client, ha_inputs, router_source, settings_store
from router_trainer.config import init_workspace, load_settings

EXPORT = {
    "version": "0.1.8",
    "language": "pl",
    "router_yaml": "household: Tomek\ntopics: {}\n",
    "tests": {"model_test.yaml": "router: []\n"},
    "log": [
        {"timestamp": "1", "text": "Jaka jutro pogoda?", "response": "", "route": "pogoda"},
        {"timestamp": "2", "text": "Kto; pyta?", "response": "x", "route": ""},
    ],
    "automations": [
        {
            "id": "kawa",
            "alias": "Kawa",
            "triggers": [{"trigger": "conversation", "command": ["zrób kawę"]}],
        },
        {
            "id": "lekcje",
            "alias": "Lekcje",
            "trigger": {"platform": "conversation", "command": "o której {dziecko} kończy"},
        },
    ],
    "custom_sentences": [{"language": "pl", "name": "dom.yaml", "text": "language: pl\n"}],
}


def connected(tmp_path, url="http://ha.test:8123"):
    ws = init_workspace(tmp_path / "ws")
    (ws.root / "ha_token").write_text("secret\n")
    (ws.root / "home_assistant.json").write_text(json.dumps({"url": url, "token_file": "ha_token"}))
    return ws


# --- saving the export ------------------------------------------------------------------------


def test_save_writes_the_files_the_generators_read(tmp_path) -> None:
    from router_trainer.generate.router import conversation_triggers

    ws = connected(tmp_path)
    inputs = ws.root / "inputs"
    old = inputs / "ha_config" / "packages" / "stary.yaml"  # a copy of the old share
    old.parent.mkdir(parents=True)
    old.write_text("automation: []\n")
    (inputs / "model_test_data.yaml").write_text("old\n")

    summary = ha_inputs.save(ws, EXPORT)

    assert (inputs / "router.yaml").read_text() == EXPORT["router_yaml"]
    assert (inputs / "model_test.yaml").read_text() == "router: []\n"
    assert not (inputs / "model_test_data.yaml").exists()  # HA has none any more
    assert not old.exists()  # stale package triggers gone
    with (inputs / "unrecognized_commands.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert [r["text"] for r in rows] == ["Jaka jutro pogoda?", "Kto; pyta?"]
    triggers = conversation_triggers(inputs / "ha_config")
    assert {t["id"]: t["templates"] for t in triggers} == {
        "kawa": ["zrób kawę"],
        "lekcje": ["o której {dziecko} kończy"],
    }
    assert (inputs / "ha_config" / "custom_sentences" / "pl" / "dom.yaml").exists()
    assert summary["version"] == "0.1.8" and summary["automations"] == 2
    assert ha_inputs.last(ws)["log_rows"] == 2


def test_save_keeps_paths_inside_the_workspace(tmp_path) -> None:
    ws = connected(tmp_path)
    bad = {**EXPORT, "custom_sentences": [{"language": "../..", "name": "../x.yaml", "text": "x"}]}
    ha_inputs.save(ws, bad)
    assert not (tmp_path / "x.yaml").exists()
    assert ha_inputs.log_csv([]) == ""


def test_websocket_url() -> None:
    assert ha_inputs.websocket_url("http://ha:8123/") == "ws://ha:8123/api/websocket"
    assert ha_inputs.websocket_url("https://dom.pl") == "wss://dom.pl/api/websocket"


# --- the export over a WebSocket like Home Assistant's ------------------------------------------


class FakeHomeAssistant:
    """aiohttp WebSocket server answering like HA: auth, then the export command."""

    def __init__(self, answer: dict, token: str = "secret", reply=None) -> None:
        self.answer = answer
        self.reply = reply  # message -> answer, for several commands on one socket
        self.messages: list[dict] = []
        self.token = token
        self.loop = asyncio.new_event_loop()
        self.port = 0

    async def handler(self, request):
        from aiohttp import web

        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "auth_required"})
        auth = await socket.receive_json()
        if auth.get("access_token") != self.token:
            await socket.send_json({"type": "auth_invalid"})
            await socket.close()
            return socket
        await socket.send_json({"type": "auth_ok"})
        while True:
            try:
                message = await socket.receive_json()
            except TypeError:  # the client closed the socket
                break
            self.messages.append(message)
            answer = self.reply(message) if self.reply else self.answer
            await socket.send_json({"id": message["id"], "type": "result", **answer})
            if not self.reply:
                break
        await socket.close()
        return socket

    def __enter__(self):
        from aiohttp import web

        async def start():
            app = web.Application()
            app.router.add_get("/api/websocket", self.handler)
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            site = web.TCPSite(self.runner, "127.0.0.1", 0)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]

        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(start(), self.loop).result(5)
        return self

    def __exit__(self, *args):
        asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def no_socket_block():
    pytest.importorskip("aiohttp")


def test_fetch_over_the_websocket(tmp_path, no_socket_block) -> None:
    with FakeHomeAssistant({"success": True, "result": EXPORT}) as ha:
        ws = connected(tmp_path, f"http://127.0.0.1:{ha.port}")
        assert ha_inputs.fetch(ws)["version"] == "0.1.8"
    assert (ws.root / "inputs" / "router.yaml").exists()


def test_old_router_and_no_administrator_are_said(tmp_path, no_socket_block) -> None:
    for error, said in (
        ({"code": "unknown_command", "message": "Unknown command."}, "too old"),
        ({"code": "unauthorized", "message": "Unauthorized"}, "administrator"),
    ):
        with FakeHomeAssistant({"success": False, "error": error}) as ha:
            ws = connected(tmp_path / error["code"], f"http://127.0.0.1:{ha.port}")
            with pytest.raises(ha_client.HaError, match=said):
                ha_inputs.fetch(ws)


def test_a_rejected_token_is_remembered(tmp_path, no_socket_block) -> None:
    with FakeHomeAssistant({"success": True, "result": EXPORT}, token="other") as ha:
        ws = connected(tmp_path, f"http://127.0.0.1:{ha.port}")
        with pytest.raises(ha_client.TokenRejected):
            ha_inputs.fetch(ws)
        with pytest.raises(ha_client.TokenRejected, match="anew"):  # never sent again
            ha_inputs.fetch(ws)


def test_unreachable_home_assistant(tmp_path, no_socket_block) -> None:
    ws = connected(tmp_path, "http://127.0.0.1:9")
    with pytest.raises(ha_client.HaError, match=r"cannot be reached|127\.0\.0\.1"):
        ha_inputs.fetch(ws)


def _home_recordings(audio: dict[str, bytes], part: int = 2):
    """Answers of Assist Router 0.1.11: the list, then at most ``part`` files per call."""
    import base64

    def reply(message):
        if message["type"] == ha_inputs.RECORDINGS:
            files = [{"path": p, "size": len(d), "modified": 0} for p, d in audio.items()]
            return {"success": True, "result": {"configured": True, "files": files}}
        if message["type"] == ha_inputs.RECORDING_FILES:
            served = [p for p in message["paths"] if p in audio][:part]
            data = [{"path": p, "data": base64.b64encode(audio[p]).decode()} for p in served]
            return {"success": True, "result": {"files": data}}
        return {"success": True, "result": EXPORT}

    return reply


def test_recordings_come_once(tmp_path, no_socket_block) -> None:
    audio = {
        "dev/Kuchnia/1/01_stt.wav": b"aa",
        "dev/Salon/2/01_stt.wav": b"bbb",
        "Salon/3/01_stt.wav": b"c",
        "../outside.wav": b"x",  # never written outside inputs/recordings
    }
    with FakeHomeAssistant({}, reply=_home_recordings(audio)) as ha:
        ws = connected(tmp_path, f"http://127.0.0.1:{ha.port}")
        summary = ha_inputs.fetch_all(ws)
        assert summary["version"] == "0.1.8"
        assert summary["recordings"] == {
            "configured": True, "in_home_assistant": 4, "fetched": 3, "missing": 0,
        }  # fmt: skip
        folder = ha_inputs.recordings_folder(ws)
        assert (folder / "dev" / "Salon" / "2" / "01_stt.wav").read_bytes() == b"bbb"
        assert not (folder.parent / "outside.wav").exists()
        again = ha_inputs.fetch_recordings(ws)  # the same sizes here: nothing is asked for
        assert again["fetched"] == 0
        assert ha.messages[-1]["type"] == ha_inputs.RECORDINGS


def test_an_older_router_without_recordings_is_said(tmp_path, no_socket_block) -> None:
    def reply(message):
        if message["type"] == ha_inputs.COMMAND:
            return {"success": True, "result": EXPORT}
        return {"success": False, "error": {"code": "unknown_command", "message": "Unknown"}}

    with FakeHomeAssistant({}, reply=reply) as ha:
        ws = connected(tmp_path, f"http://127.0.0.1:{ha.port}")
        recordings = ha_inputs.fetch_all(ws)["recordings"]
    assert recordings["fetched"] == 0 and "0.1.11" in recordings["error"]


def test_recordings_switched_off_are_not_asked_for(tmp_path, no_socket_block) -> None:
    with FakeHomeAssistant({}, reply=_home_recordings({"a/01_stt.wav": b"a"})) as ha:
        ws = connected(tmp_path, f"http://127.0.0.1:{ha.port}")
        ws.config_file.write_text("generate:\n  router:\n    recordings: false\n", "utf-8")
        assert "recordings" not in ha_inputs.fetch_all(ws)
        assert [m["type"] for m in ha.messages] == [ha_inputs.COMMAND]


# --- the router code -------------------------------------------------------------------------


def fake_clone(version: str):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        target = Path(command[-1])
        manifest = target / "custom_components" / "assist_router" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": version}))
        (target / "requirements_test.txt").write_text("hassil==3\n")

        class Result:
            returncode, stdout, stderr = 0, "", ""

        return Result()

    return runner, calls


def test_router_auto_uses_the_fetched_version(tmp_path, monkeypatch) -> None:
    sibling = tmp_path / "sibling"
    monkeypatch.setattr(router_source, "SIBLING", sibling)
    assert router_source.resolve(tmp_path, "auto") == sibling  # nothing fetched yet
    runner, calls = fake_clone("0.1.8")
    path = router_source.fetch(tmp_path, "v0.1.8", runner)
    assert calls[0][:6] == ["git", "clone", "--depth", "1", "--branch", "v0.1.8"]
    assert router_source.resolve(tmp_path, "auto") == path == tmp_path / "router" / "v0.1.8"
    router_source.fetch(tmp_path, "0.1.8", runner)
    assert len(calls) == 1  # already there
    state = router_source.state(tmp_path, "auto", "0.1.8")
    assert state["matches"] and state["version"] == "0.1.8" and not state["rebuild"]
    assert not router_source.state(tmp_path, "auto", "0.1.9")["matches"]
    assert router_source.resolve(tmp_path, "/x/router") == Path("/x/router")
    with pytest.raises(ValueError):
        router_source.fetch(tmp_path, "main; rm -rf /", runner)


def test_router_requirements_changed(tmp_path, monkeypatch) -> None:
    image = tmp_path / "image-requirements.txt"
    image.write_text("hassil==2\n")
    monkeypatch.setattr(router_source, "IMAGE_REQUIREMENTS", str(image))
    runner, _ = fake_clone("0.1.8")
    path = router_source.fetch(tmp_path, "0.1.8", runner)
    assert router_source.requirements_changed(path)
    image.write_text("hassil==3\n")
    assert not router_source.requirements_changed(path)


def test_failed_clone_is_said(tmp_path) -> None:
    def runner(command, **kwargs):
        class Result:
            returncode, stdout, stderr = 128, "", "fatal: Remote branch v9.9.9 not found"

        return Result()

    with pytest.raises(RuntimeError, match=r"v9\.9\.9 not found"):
        router_source.fetch(tmp_path, "9.9.9", runner)


def test_load_settings_resolves_auto(tmp_path, monkeypatch) -> None:
    ws = init_workspace(tmp_path / "ws")
    runner, _ = fake_clone("0.1.8")
    router_source.fetch(ws.root, "0.1.8", runner)
    settings = load_settings(ws)
    assert settings["router_repo_setting"] == "auto"
    assert settings["router_repo"] == str(ws.root / "router" / "v0.1.8")


# --- trainer.yaml from the panel ---------------------------------------------------------------


def test_settings_check() -> None:
    assert settings_store.check("dataset: {dev_fraction: 0.1}\n")["ok"]
    bad = settings_store.check("dataset: {dev_fraction: 2}\nmodels: {e4b: {epochs: x}}\n")
    assert not bad["ok"] and "dev_fraction" in bad["error"] and "epochs" in bad["error"]
    assert not settings_store.check("a: [")["ok"]
    assert not settings_store.check("- 1\n")["ok"]
    assert settings_store.check("nowa: 1\n")["warnings"] == ["unknown section: nowa"]


def test_settings_draft_save_history_restore(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    loaded = settings_store.load(ws)
    original = loaded["text"]
    settings_store.save_draft(ws, original + "\nholdout: {word_similarity: 0.7}\n", loaded["hash"])
    assert settings_store.load(ws)["draft"]["text"].endswith("0.7}\n")
    assert ws.config_file.read_text() == original  # a draft changes nothing
    with pytest.raises(ValueError):
        settings_store.save(ws, "dataset: {dev_fraction: 9}\n", loaded["hash"])
    new = original + "\nholdout: {word_similarity: 0.7}\n"
    saved = settings_store.save(ws, new, loaded["hash"], note="mniej podobnych", user="tomek")
    assert ws.config_file.read_text() == new and saved["ok"]
    assert saved["hash"] == settings_store.text_hash(new)
    assert settings_store.load(ws)["draft"] is None
    assert (ws.root / "trainer.yaml.bak").read_text() == original
    versions = settings_store.versions(ws)
    assert versions[0]["note"] == "mniej podobnych" and versions[0]["user"] == "tomek"
    assert "text" not in versions[0] and versions[0]["time"]
    assert load_settings(ws)["holdout"]["word_similarity"] == 0.7
    # a draft begun before the last save: outdated, and saving it is a conflict
    settings_store.save_draft(ws, original, loaded["hash"])
    assert settings_store.load(ws)["draft"]["outdated"] is True
    with pytest.raises(settings_store.Conflict):
        settings_store.save(ws, original, loaded["hash"])
    assert settings_store.save(ws, original, loaded["hash"], force=True)["ok"]  # "Save anyway"
    restored = settings_store.restore(ws, versions[0]["id"])
    assert restored["text"] == original
    assert settings_store.load(ws)["draft"]["text"] == original
    assert settings_store.load(ws)["draft"]["outdated"] is False
    assert ws.config_file.read_text() == original  # restored only as a draft
    settings_store.discard(ws)
    assert settings_store.load(ws)["draft"] is None
    with pytest.raises(ValueError):
        settings_store.history_get(ws, "nope")
    assert yaml.safe_load(new)["holdout"]["word_similarity"] == 0.7


def test_pairs_lists_and_maps_are_checked_on_save() -> None:
    good = (
        "generate: {router: {contrast: {pairs: auto, extra: [[czytania, wiadomosci]]}}}\n"
        "topic_overrides: {asystent_czytania: czytania}\nslot_values: {kto: [Ania, Tomek]}\n"
    )
    assert settings_store.check(good)["ok"]
    assert settings_store.check("generate: {router: {contrast: {pairs: [[a, b], [c, d]]}}}\n")["ok"]
    for bad, where in [
        ("generate: {router: {contrast: {pairs: [[a]]}}}\n", "contrast.pairs"),
        ("generate: {router: {contrast: {pairs: sometimes}}}\n", "contrast.pairs"),
        ("generate: {router: {contrast: {extra: [czytania]}}}\n", "contrast.extra"),
        ("topic_overrides: [a, b]\n", "topic_overrides"),
        ("slot_values: {kto: Ania}\n", "slot_values.kto"),
    ]:
        result = settings_store.check(bad)
        assert not result["ok"] and where in result["error"], bad
