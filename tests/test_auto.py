"""Automatic training (one job from Home Assistant to a compared model), its summary, and
Assist Router's router model changed through Home Assistant's options flow."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from router_trainer import assist_router_model, auto, ha_client, pipeline
from router_trainer.config import init_workspace

from .test_panel import FakeBackend

# --- the verdict --------------------------------------------------------------------------------


def test_scores_are_read_in_any_form() -> None:
    assert auto.score(0.9) == 0.9 and auto.score("27/28") == pytest.approx(27 / 28)
    assert auto.score("0.5") == 0.5
    assert auto.score(None) is None and auto.score("x/y") is None and auto.score("1/0") is None


def _report(trained, base, trained_s, base_s, fixed=(), broken=()) -> dict:
    return {
        "trained": "assist-router-e2b-ft:r",
        "base": "gemma4:26b",
        "parts": {
            "router": {
                "trained": trained,
                "base": base,
                "trained_s": trained_s,
                "base_s": base_s,
                "fixed": list(fixed),
                "broken": list(broken),
            },
            "answers": {"trained": "1/10", "base": "10/10", "trained_s": 9, "base_s": 1},
        },
    }


@pytest.mark.parametrize(
    ("trained", "base", "trained_s", "base_s", "accurate", "faster", "better"),
    [
        ("370/379", "365/379", 0.2, 0.9, True, True, True),
        ("365/379", "365/379", 0.2, 0.9, True, True, True),  # as accurate and faster
        ("370/379", "365/379", 1.2, 0.9, True, False, False),  # not faster
        ("360/379", "365/379", 0.2, 0.9, False, True, False),  # less accurate
    ],
)
def test_the_verdict_judges_the_router_part(
    trained, base, trained_s, base_s, accurate, faster, better
) -> None:
    verdict = auto.verdict(
        _report(trained, base, trained_s, base_s, fixed=["a"], broken=["b", "c"])
    )
    assert (verdict["accurate"], verdict["faster"], verdict["better"]) == (accurate, faster, better)
    assert verdict["fixed"] == 1 and verdict["broken"] == 2
    assert auto.verdict({"parts": {}})["better"] is False


def _compare(ws, run: str, report: dict) -> None:
    folder = ws.run(run)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "compare.json").write_text(json.dumps(report), encoding="utf-8")


def test_the_summary_recommends_the_most_accurate_better_model(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    _compare(ws, "home-e2b", _report("366/379", "365/379", 0.2, 0.9))
    _compare(ws, "home-e4b", _report("372/379", "365/379", 0.4, 0.9))
    summary = auto.summarize(ws, "home", ["e2b", "e4b", "e9b"])
    assert summary["recommended"] == "home-e4b"
    e2b, e4b, missing = summary["models"]
    assert e2b["ollama"] == "assist-router-e2b-ft:home-e2b" and e2b["better"]
    assert e4b["base_model"] == "gemma4:26b" and missing["missing"]
    assert auto.latest(ws) == summary
    _compare(ws, "worse-e2b", _report("300/379", "365/379", 0.2, 0.9))
    assert auto.summarize(ws, "worse", ["e2b"])["recommended"] is None


def test_without_any_summary_latest_is_none(tmp_path) -> None:
    assert auto.latest(init_workspace(tmp_path / "ws")) is None


# --- the run ----------------------------------------------------------------------------------------


@pytest.fixture
def steps(tmp_path, monkeypatch):
    """auto.run with Home Assistant, the router code, the test and the pipeline replaced."""
    ws = init_workspace(tmp_path / "ws")
    seen: dict = {"fetched": [], "active": None}
    monkeypatch.setattr(auto.ha_inputs, "fetch", lambda ws: {"version": "0.1.9", "log_rows": 3})
    monkeypatch.setattr(auto.ha_inputs, "fetch_recordings", lambda ws: {"fetched": 0})
    monkeypatch.setattr(
        auto.router_source, "state", lambda root, configured, version: {"matches": False}
    )
    monkeypatch.setattr(
        auto.router_source, "fetch", lambda root, version: seen["fetched"].append(version)
    )
    from router_trainer.testset import build as testset_build, store

    monkeypatch.setattr(store, "set_active", lambda ws, name: seen.__setitem__("active", name))
    monkeypatch.setattr(testset_build, "build", lambda ctx, name: seen.__setitem__("written", name))
    from router_trainer import context

    monkeypatch.setattr(context, "make", lambda ws: "ctx")

    def run(ws, steps, dataset, models, upload=True, **kwargs):
        seen["pipeline"] = (steps, dataset, models, upload)
        for model in models:
            _compare(ws, pipeline.run_name(dataset, model), _report("366/379", "365/379", 0.2, 0.9))
        return 0

    monkeypatch.setattr(auto.pipeline, "run", run)
    return ws, seen


def test_a_run_takes_the_whole_road_with_the_ha_test(steps, capsys) -> None:
    ws, seen = steps
    tests = ws.root / "inputs" / "model_test.yaml"
    tests.parent.mkdir(parents=True, exist_ok=True)
    tests.write_text("router: []\n", encoding="utf-8")
    assert auto.run(ws, "home", ["e2b"]) == 0
    assert seen["fetched"] == ["0.1.9"] and seen["active"] == "ha" and "written" not in seen
    steps_run, dataset, models, upload = seen["pipeline"]
    assert "testgen" not in steps_run and steps_run[0] == "snapshot" and steps_run[-1] == "evaluate"
    assert (dataset, models, upload) == ("home", ["e2b"], True)
    out = capsys.readouterr().out
    assert "recommended: home-e2b" in out and f"{auto.RESULT} " in out
    assert auto.summary_path(ws, "home").is_file()


def test_a_run_can_write_a_new_test_and_skip_the_upload(steps) -> None:
    ws, seen = steps
    auto.run(ws, "home", ["e2b"], test=auto.TEST_NEW, upload=False)
    assert seen["written"] == "home" and seen["active"] == "home"
    assert "evaluate" not in seen["pipeline"][0] and seen["pipeline"][3] is False


def test_a_router_only_run_generates_no_commands_or_answers(steps) -> None:
    ws, seen = steps
    seen["roles"] = None
    original = auto.pipeline.run

    def run(ws, steps, dataset, models, upload=True, roles=None, **kwargs):
        seen["roles"] = roles
        return original(ws, steps, dataset, models, upload=upload)

    auto.pipeline.run = run
    try:
        auto.run(ws, "home", ["e2b"], test=auto.TEST_NEW, roles=("router",))
    finally:
        auto.pipeline.run = original
    steps_run = seen["pipeline"][0]
    assert "router" in steps_run and "control" not in steps_run and "answers" not in steps_run
    assert seen["roles"] == ("router",)
    with pytest.raises(ValueError, match="router role"):
        auto.run(ws, "home", ["e2b"], test=auto.TEST_NEW, roles=("control",))


def test_a_run_refuses_what_it_cannot_do(steps) -> None:
    ws, _ = steps
    with pytest.raises(FileNotFoundError, match=r"model_test\.yaml"):
        auto.run(ws, "home", ["e2b"])  # no test from Home Assistant
    with pytest.raises(ValueError):
        auto.run(ws, "../x", ["e2b"])
    with pytest.raises(ValueError, match="model"):
        auto.run(ws, "home", [])


def test_the_panel_starts_the_automatic_job(tmp_path) -> None:
    from router_trainer.ui import server as server_module

    panel = server_module.Panel(init_workspace(tmp_path / "ws"))
    panel._backend = FakeBackend()
    panel.start({"kind": "auto", "dataset": "home-20261118", "models": ["e2b", "e4b"]})
    kind, title, args = panel._backend.started[-1]
    assert kind == "auto" and "home-20261118" in title
    assert args == ["auto", "--dataset", "home-20261118", "--models", "e2b", "e4b", "--test", "ha"]
    panel.start(
        {
            "kind": "auto",
            "dataset": "h",
            "models": ["e2b"],
            "test": "new",
            "upload": False,
            "router_only": True,
        }
    )
    assert panel._backend.started[-1][2][-5:] == [
        "--test",
        "new",
        "--roles",
        "router",
        "--no-upload",
    ]
    for bad in ({"kind": "auto", "dataset": "h", "models": []},
                {"kind": "auto", "dataset": "h", "models": ["e2b"], "test": "x"},
                {"kind": "auto", "dataset": "h", "models": ["../e2b"]}):  # fmt: skip
        with pytest.raises(ValueError):
            panel.start(bad)


# --- Assist Router's router model in Home Assistant -----------------------------------------------


class FakeHa:
    """Home Assistant's options flow of Assist Router: menu → router step → form → entry."""

    def __init__(self, models=("gemma4:26b", "assist-router-e2b-ft:home-e2b")) -> None:
        self.models = list(models)
        self.options = {
            "router_model": "gemma4:26b",
            "answer_model": "gemma4:26b",
            "answer_timeout": 30,
            "router_timeout": 10,
            "router_keep_alive": -1,
        }
        self.deleted: list[str] = []
        self.sent: list[dict] = []

    def form(self) -> dict:
        o = self.options
        return {
            "type": "form",
            "flow_id": "f1",
            "step_id": "router",
            "data_schema": [
                {
                    "name": "router_model",
                    "required": True,
                    "default": o["router_model"],
                    "selector": {"select": {"options": self.models, "mode": "dropdown"}},
                },
                {
                    "name": "answer_model",
                    "optional": True,
                    "description": {"suggested_value": o["answer_model"]},
                },
                {"name": "answer_timeout", "required": True, "default": o["answer_timeout"]},
                {"name": "router_timeout", "required": True, "default": o["router_timeout"]},
                {"name": "router_keep_alive", "required": True, "default": o["router_keep_alive"]},
            ],
        }

    def handle(self, method: str, path: str, body: dict | None):
        if method == "GET" and path.startswith(
            "/api/config/config_entries/entry?domain=assist_router"
        ):
            return [{"entry_id": "e1", "state": "loaded"}]
        if method == "POST" and path == "/api/config/config_entries/options/flow":
            assert body == {"handler": "e1"}
            return {"type": "menu", "flow_id": "f1", "step_id": "init"}
        if method == "POST" and path == "/api/config/config_entries/options/flow/f1":
            if body == {"next_step_id": "router"}:
                return self.form()
            self.sent.append(body)
            self.options = {**self.options, **body}
            return {"type": "create_entry"}
        if method == "DELETE" and path == "/api/config/config_entries/options/flow/f1":
            self.deleted.append(path)
            return None
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def ha(tmp_path):
    fake = FakeHa()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self, method):
            assert self.headers["Authorization"] == "Bearer secret"
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            result = fake.handle(method, self.path, body)
            data = b"" if result is None else json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._answer("GET")

        def do_POST(self):
            self._answer("POST")

        def do_DELETE(self):
            self._answer("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    connection = ha_client.Connection(f"http://127.0.0.1:{server.server_address[1]}", "secret")
    ws = init_workspace(tmp_path / "ws")
    yield fake, ha_client.Client(connection), ws
    server.shutdown()
    server.server_close()


def test_the_router_model_is_read_without_changing_anything(ha) -> None:
    fake, client, _ = ha
    assert assist_router_model.current(client) == {
        "model": "gemma4:26b",
        "choices": ["gemma4:26b", "assist-router-e2b-ft:home-e2b"],
    }
    assert fake.sent == [] and len(fake.deleted) == 1


def test_using_a_model_keeps_the_other_options_and_can_be_restored(ha) -> None:
    fake, client, ws = ha
    result = assist_router_model.use(client, ws, "assist-router-e2b-ft:home-e2b")
    assert result == {"model": "assist-router-e2b-ft:home-e2b", "previous": "gemma4:26b"}
    assert fake.sent[-1] == {
        "router_model": "assist-router-e2b-ft:home-e2b",
        "answer_model": "gemma4:26b",
        "answer_timeout": 30,
        "router_timeout": 10,
        "router_keep_alive": -1,
    }
    assert assist_router_model.remembered(ws)["previous"] == "gemma4:26b"
    assert assist_router_model.restore(client, ws)["model"] == "gemma4:26b"
    assert fake.options["router_model"] == "gemma4:26b"
    assert assist_router_model.remembered(ws) is None
    with pytest.raises(ValueError, match="no earlier"):
        assist_router_model.restore(client, ws)


def test_a_model_missing_in_ollama_is_refused(ha) -> None:
    fake, client, ws = ha
    with pytest.raises(ha_client.HaError, match="not in the home Ollama"):
        assist_router_model.use(client, ws, "assist-router-e4b-ft:home-e4b")
    assert fake.sent == [] and fake.deleted and fake.options["router_model"] == "gemma4:26b"
