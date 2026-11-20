"""The teacher of each role: the trainer's Ollama, an OpenAI-compatible API, Claude or by hand."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import stat
import threading

import pytest

from router_trainer import handoff, settings_store, teacher
from router_trainer.generate import build, control, labels
from router_trainer.generate.common import read_jsonl
from tests.conftest import needs_router


class FakeAPI:
    """A local HTTP server answering with the replies of a list, recording every request."""

    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[str, dict, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                outer.requests.append(
                    (self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                )
                status, reply = outer.replies.pop(0)
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    servers = []

    def start(replies):
        server = FakeAPI(replies)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


SCHEMA = {
    "type": "object",
    "properties": {"zdania": {"type": "array", "items": {"type": "string"}}},
}
MESSAGES = [{"role": "system", "content": "Bądź zwięzły."}, {"role": "user", "content": "Napisz"}]


def _openai(content: str) -> tuple[int, dict]:
    return 200, {"choices": [{"message": {"content": content}}]}


def test_an_openai_compatible_api_gets_the_schema(api) -> None:
    server = api([_openai('{"zdania": ["Włącz światło"]}'), _openai("Dzień dobry.")])
    model = teacher.OpenAITeacher(server.url, "local-model", "sk-test")
    assert model.json(MESSAGES, SCHEMA, temperature=0.9, num_predict=50, seed=7) == {
        "zdania": ["Włącz światło"]
    }
    path, headers, body = server.requests[0]
    assert path == "/chat/completions" and headers["authorization"] == "Bearer sk-test"
    sent = body["response_format"]["json_schema"]["schema"]
    assert sent["additionalProperties"] is False and sent["required"] == ["zdania"]
    assert body["seed"] == 7 and body["temperature"] == 0.9
    assert model.text(MESSAGES) == "Dzień dobry."


def test_a_server_without_schemas_is_asked_in_words_and_limits_wait(api) -> None:
    server = api([
        (429, {"error": "slow down"}),
        (400, {"error": "response_format json_schema is not supported"}),
        _openai('Oto odpowiedź: ```json\n{"zdania": ["a"]}\n```'),
        _openai('{"zdania": ["b"]}'),
    ])  # fmt: skip
    model = teacher.OpenAITeacher(server.url, "m", "")
    assert model.json(MESSAGES, SCHEMA) == {"zdania": ["a"]}
    assert "response_format" not in server.requests[2][2]
    assert "JSON only" in server.requests[2][2]["messages"][-1]["content"]
    assert model.json(MESSAGES, SCHEMA) == {"zdania": ["b"]}  # not asked with a schema again
    assert "authorization" not in server.requests[0][1]


def _claude(text: str, stop: str = "end_turn") -> tuple[int, dict]:
    return 200, {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}] if text else [], "stop_reason": stop,
        "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 4},
    }  # fmt: skip


def test_claude_answers_by_structured_outputs_with_a_fallback(api) -> None:
    server = api([_claude('{"zdania": ["Zgaś lampę"]}'), _claude("", stop="refusal")])
    model = teacher.ClaudeTeacher("claude-opus-5-5", "sk-ant-test", "low", server.url)
    assert model.json(MESSAGES, SCHEMA, temperature=1.0, seed=3) == {"zdania": ["Zgaś lampę"]}
    path, headers, body = server.requests[0]
    assert path.startswith("/v1/messages")
    assert "sk-ant-test" in (headers.get("x-api-key", "") + headers.get("authorization", ""))
    assert "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["fallbacks"] == "default" and body["system"] == "Bądź zwięzły."
    assert body["messages"] == [{"role": "user", "content": "Napisz"}]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in body and "seed" not in body  # not taken by current models
    assert model.json(MESSAGES, SCHEMA) is None  # declined: no answer, nothing invented


def test_answers_of_an_api_are_remembered(tmp_path) -> None:
    class Inner:
        model = "m"
        calls = 0

        def json(self, messages, schema, **options):
            self.calls += 1
            return None if messages[-1]["content"] == "pusto" else {"zdania": ["x"]}

        def text(self, messages, **options):
            self.calls += 1
            return "odpowiedź"

    inner = Inner()
    cached = teacher.CachedTeacher(inner, tmp_path / "writer.jsonl")
    for _ in range(2):
        assert cached.json(MESSAGES, SCHEMA, temperature=0.5) == {"zdania": ["x"]}
        assert cached.text(MESSAGES) == "odpowiedź"
    assert inner.calls == 2
    again = teacher.CachedTeacher(inner, tmp_path / "writer.jsonl")  # a resumed step
    assert again.json(MESSAGES, SCHEMA, temperature=0.5) == {"zdania": ["x"]} and inner.calls == 2
    assert again.json(MESSAGES, SCHEMA, temperature=0.1) == {"zdania": ["x"]} and inner.calls == 3
    empty = [{"role": "user", "content": "pusto"}]
    cached.json(empty, SCHEMA), cached.json(empty, SCHEMA)
    assert inner.calls == 5  # no answer is not remembered


def test_each_role_has_its_own_teacher(tmp_path, monkeypatch) -> None:
    settings = {"ollama": {"teacher": "gemma4:26b", "test_writer": "bielik", "local_port": 1}}
    assert teacher.role_settings(settings, "judge")["model"] == "gemma4:26b"
    assert teacher.role_settings(settings, "test_writer")["model"] == "bielik"
    settings["teacher"] = {
        "writer": {"provider": "claude"},
        "judge": {"provider": "manual"},
        "test_writer": {"provider": "openai", "model": "local", "base_url": "http://lm:1234/v1"},
    }
    assert teacher.role_settings(settings, "writer")["model"] == "claude-opus-5-5"
    assert teacher.is_manual(settings, "judge") and not teacher.is_manual(settings, "writer")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no Claude API key"):
        teacher.make(settings, tmp_path, "writer")
    teacher.save_key(tmp_path, "claude", " sk-ant-x \n")
    key_file = teacher.secret_path(tmp_path, "claude")
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600 and teacher.has_key(tmp_path, "claude")
    made = teacher.make(settings, tmp_path, "writer")
    assert isinstance(made, teacher.CachedTeacher) and made.inner.model == "claude-opus-5-5"
    with pytest.raises(teacher.ManualRole, match="judge"):
        teacher.make(settings, tmp_path, "judge").json(MESSAGES, SCHEMA)
    assert teacher.make(settings, tmp_path, "test_writer").inner.url == "http://lm:1234/v1"
    teacher.save_key(tmp_path, "claude", "")
    assert not key_file.exists()
    with pytest.raises(ValueError, match="unknown teacher role"):
        teacher.make(settings, tmp_path, "boss")


def test_the_settings_check_the_teacher() -> None:
    bad = settings_store.check("teacher:\n  writer: {provider: gpt}\n  boss: {provider: ollama}\n")
    assert not bad["ok"] and "teacher.writer.provider" in bad["error"] and "boss" in bad["error"]
    unnamed = settings_store.check("teacher:\n  judge: {provider: openai}\n")
    assert "name the model" in unnamed["error"]
    claude = settings_store.check("teacher:\n  writer: {provider: claude}\n")
    assert claude["ok"] and any("household" in w for w in claude["warnings"])


# --- by hand ------------------------------------------------------------------------------------


def _manual(ctx, *roles) -> None:
    ctx.settings["teacher"] = {role: {"provider": "manual"} for role in roles}


@needs_router
def test_the_writer_by_hand_round_trip(ctx, tmp_path) -> None:
    _manual(ctx, "writer")
    ctx.settings["generate"]["control"]["labels"] = 3
    ctx.settings["generate"]["router"]["contrast"] = {"per_side": 5, "pairs": [["pogoda", "inne"]]}
    exported = handoff.export(ctx, "writer", tmp_path / "out", per_topic=25)
    ids = [json.loads(line)["id"] for line in (tmp_path / "out" / "requests.jsonl").open()]
    kinds = {task_id.split(":")[0] for task_id in ids}
    assert kinds == {"paraphrase", "contrast", "control"} and exported["tasks"] == len(ids)
    assert "## Part 1" in (tmp_path / "out" / "prompts.md").read_text(encoding="utf-8")
    assert "handoff import writer" in (tmp_path / "out" / "README.md").read_text(encoding="utf-8")
    weather = next(i for i in ids if i.startswith("paraphrase:pogoda"))
    pair = next(i for i in ids if i.startswith("contrast:"))
    pasted = (
        "Sure! Here are the answers:\n"
        f'{{"id": "{weather}", "zdania": ["Czy w sobotę będzie słońce?", "Włącz światło w kuchni"]}}\n'
        f'[{{"id": "{pair}", "temat_a": ["Opowiedz kawał"], "temat_b": ["Czy jutro pada?"]}},\n'
        ' {"id": "control:1", "zdania": ["Odkurz salon"]}, {"id": "nope", "zdania": ["x"]}]'
    )
    answers = tmp_path / "answers.txt"
    answers.write_text(pasted, encoding="utf-8")
    result = handoff.import_answers(ctx, "writer", answers)
    assert result == {"role": "writer", "answers": 3, "sentences": 4, "like_test": 1,
                      "unknown_task": 1}  # fmt: skip
    rows = {(r["text"], r["topic"]) for r in read_jsonl(ctx.ws.generated / "router.jsonl")}
    assert rows == {("Czy w sobotę będzie słońce?", "pogoda"), ("Opowiedz kawał", "inne"),
                    ("Czy jutro pada?", "pogoda")}  # fmt: skip
    assert control.external_sentences(ctx) == {1: ["Odkurz salon"]}
    again = handoff.export(ctx, "writer", tmp_path / "again", per_topic=25)
    assert again["tasks"] == len(ids) - 3  # the answered ones are not asked again


@needs_router
def test_the_judge_by_hand_round_trip(ctx, tmp_path) -> None:
    _manual(ctx, "judge")
    path = ctx.ws.generated / "router.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [("Czy pada w Gdańsku?", "pogoda", "paraphrase"), ("Opowiedz bajkę", "inne", "external"),
            ("Zgaś lampkę", "sterowanie", "intent")]  # fmt: skip
    path.write_text("".join(json.dumps({"role": "router", "part": s, "text": t, "topic": p,
                                        "source": s}, ensure_ascii=False) + "\n"
                            for t, p, s in rows), encoding="utf-8")  # fmt: skip
    checker = labels.Checker(ctx)
    assert checker.manual
    assert labels.clean(ctx, checker) == 0  # nothing judged yet - nothing dropped
    chosen = {r["source"].split("+")[0] for r in build.router_rows(ctx, ctx.rng("b"))}
    assert chosen == {"intent"}  # the checked ones wait for the judge (small topics padded)
    exported = handoff.export(ctx, "judge", tmp_path / "judge")
    assert exported["tasks"] == 2
    table = (tmp_path / "judge" / "table.csv").read_text(encoding="utf-8")
    assert table.splitlines()[0] == "text;topic"
    filled = tmp_path / "filled.csv"
    filled.write_text("text;topic\nCzy pada w Gdańsku?;pogoda\nOpowiedz bajkę;nieznany\n",
                      encoding="utf-8")  # fmt: skip
    assert handoff.import_answers(ctx, "judge", filled) == {"role": "judge", "judged": 1,
                                                            "unknown_topic": 1}  # fmt: skip
    task = json.loads((tmp_path / "judge" / "requests.jsonl").read_text().splitlines()[-1])
    assert task["messages"][0]["role"] == "system"  # the router's own prompt for an AI chat
    answer = tmp_path / "answer.jsonl"
    answer.write_text(json.dumps({"id": task["id"], "temat": "sterowanie"}), encoding="utf-8")
    handoff.import_answers(ctx, "judge", answer)
    assert labels.clean(ctx, labels.Checker(ctx)) == 1  # „Opowiedz bajkę” is not „inne”
    assert handoff.export(ctx, "judge", tmp_path / "none")["tasks"] == 0


@needs_router
def test_commands_of_a_manual_writer_are_parsed_by_the_judge(ctx, monkeypatch) -> None:
    from tests.test_generate import FakeTeacher

    _manual(ctx, "writer")
    ctx.settings["generate"]["control"]["labels"] = 2
    plans = control.plans(ctx, ctx.home)
    handoff.folder(ctx).mkdir(parents=True, exist_ok=True)
    (handoff.folder(ctx) / "control-external.jsonl").write_text(
        json.dumps({"label": 0, "text": "Zrób coś"}) + "\n", encoding="utf-8"
    )
    read = []
    ctx.teacher_obj = FakeTeacher(parse=lambda content: read.append(content) or None)
    control.generate(ctx)
    assert len(read) == 1 and "Zrób coś" in read[0]  # only the plan with a sentence
    assert plans == control.plans(ctx, ctx.home)  # the same plans every time
    _manual(ctx, "writer", "judge")
    with pytest.raises(RuntimeError, match="model judge"):
        control.generate(ctx)
