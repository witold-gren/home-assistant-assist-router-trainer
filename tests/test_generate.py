"""Generators without the teacher's GPU: a fake teacher answers instead."""

from __future__ import annotations

import json

from router_trainer.generate import answers, build, control, router
from router_trainer.generate.common import read_jsonl
from tests.conftest import needs_router

pytestmark = needs_router


class FakeTeacher:
    """Writes sentences and parses commands with fixed rules (no model)."""

    def __init__(self, sentences=None, parse=None, text="") -> None:
        self.sentences = sentences or []
        self.parse = parse
        self.answer = text
        self.prompts: list[str] = []

    def json(self, messages, schema, **_):
        content = messages[-1]["content"]
        self.prompts.append(content)
        key = next(iter(schema["properties"]))
        if key in ("zdania", "pytania"):
            return {key: list(self.sentences)}
        if key == "temat":
            return {"temat": "sterowanie" if "włącz" in content.lower() else "inne"}
        return self.parse(content) if self.parse else None

    def text(self, messages, **_):
        return self.answer


# --- router ---------------------------------------------------------------------------------


def test_conversation_triggers_read_automations_and_packages(tmp_path) -> None:
    (tmp_path / "packages").mkdir()
    (tmp_path / "automations.yaml").write_text(
        "- id: a1\n  alias: Kawa\n  triggers:\n  - trigger: conversation\n"
        "    command: ['zrób kawę', 'kawa [proszę]']\n  - trigger: state\n"
    )
    (tmp_path / "packages" / "p.yaml").write_text(
        "automation:\n  - id: b1\n    trigger:\n      platform: conversation\n"
        "      command: 'co jest {dzien}'\n    action: []\nsecret: !secret x\n"
    )
    found = router.conversation_triggers(tmp_path)
    assert [t["key"] for t in found] == ["a1#0", "b1#0"]
    assert found[0]["templates"] == ["zrób kawę", "kawa [proszę]"]


def test_map_triggers_override_and_reference() -> None:
    triggers = [
        {"key": "a#0", "id": "a", "alias": "", "templates": ["co jest w kalendarzu {dzien}"]},
        {"key": "b#0", "id": "b", "alias": "", "templates": ["zrób kawę"]},
    ]
    mapping = router.map_triggers(
        triggers, {"kalendarz": {"co jest w kalendarzu jutro"}}, {"b": "sterowanie"}
    )
    assert mapping == {"a#0": "kalendarz", "b#0": "sterowanie"}


def test_regex_helpers_accept_ignorecase() -> None:
    search = router._regex(lambda *a: __import__("re").search(*a) is not None)
    assert search("Jutro", "jutro", ignorecase=True)
    assert not search("Jutro", "jutro")


def test_trigger_topics_from_the_classifier_are_saved(ctx) -> None:
    folder = ctx.ws.path("inputs/ha_config")
    folder.mkdir(parents=True)
    (folder / "automations.yaml").write_text(
        "- id: k\n  alias: Kawa\n  triggers:\n  - trigger: conversation\n"
        "    command: ['włącz ekspres do kawy']\n"
    )
    out = router.trigger_sentences(ctx, ctx.home, ctx.rng("t"), lambda texts: "sterowanie")
    assert out and {topic for _, topic, _ in out} == {"sterowanie"}
    saved = json.loads((ctx.ws.generated / "trigger_topics.json").read_text())
    assert saved["k#0"]["topic"] == "sterowanie"
    # the next run takes the saved choice without asking
    again = router.trigger_sentences(ctx, ctx.home, ctx.rng("t"), None)
    assert {topic for _, topic, _ in again} == {"sterowanie"}


def test_native_intents_use_home_names_and_topics(ctx) -> None:
    ctx.settings["generate"]["router"]["native_intents"] = 300
    rows = router.native_sentences(ctx, ctx.home, ctx.rng("n"))
    topics = {topic for _, topic, _ in rows}
    assert "sterowanie" in topics and topics <= set(ctx.config.topics)


def test_gibberish_is_reproducible(ctx) -> None:
    assert router.gibberish(ctx, ctx.rng("g"), 10) == router.gibberish(ctx, ctx.rng("g"), 10)


def test_log_questions_skip_test_sentences_and_use_the_teacher(ctx) -> None:
    log = ctx.ws.path("inputs/unrecognized_commands.csv")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "﻿timestamp;area;device;kind;text;response;route;speaker\n"
        "1;;;x;Włącz światło w kuchni;;;\n"  # a test sentence
        "2;;;x;Włącz telewizor w salonie;;;\n"
        "3;;;x;Ile waży słoń?;;;\n",
        encoding="utf-8",
    )
    ctx.teacher_obj = FakeTeacher()
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        router.log_questions(ctx, writer, ctx.holdout())
    rows = {r["text"]: r["topic"] for r in read_jsonl(out)}
    assert rows == {"Włącz telewizor w salonie": "sterowanie", "Ile waży słoń?": "inne"}


def test_paraphrases_drop_test_sentences(ctx) -> None:
    ctx.settings["generate"]["router"]["paraphrases_per_topic"] = 2
    ctx.teacher_obj = FakeTeacher(["Włącz światło w kuchni", "Co Tomek ma w piątek?", "Kalendarz?"])
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        router.paraphrases(ctx, writer, ctx.holdout(), ctx.home)
    texts = {r["text"] for r in read_jsonl(out)}
    assert "Włącz światło w kuchni" not in texts
    assert "Co Tomek ma w piątek?" in texts
    assert "NIE pisz" in next(p for p in ctx.teacher_obj.prompts if "inne" in p)


# --- control --------------------------------------------------------------------------------


def test_plans_fit_the_home(ctx) -> None:
    rng = ctx.rng("p")
    kinds = set()
    for _ in range(300):
        label = control.plan(ctx, ctx.home, rng)
        if label is None:
            continue
        kinds.add(label.kind)
        assert label.fields["intent"] in ctx.integ.lang.INTENTS
        area = label.fields.get("area")
        assert area is None or area in ctx.home["areas"].values()
        assert control.details(ctx, label)
    assert {"device_on_off", "brightness", "play", "routine", "list"} <= kinds


def _command(ctx, **fields):
    return ctx.integ.parse_command(
        ctx.home, ctx.integ.control_answer(ctx.home, {"intent": "HassTurnOn", **fields})
    )


def test_matches_compares_the_parse_with_the_plan(ctx) -> None:
    label = control.Label("brightness", {"intent": "HassTurnOn", "domain": "light",
                                         "area": "Salon", "value": 40})  # fmt: skip
    assert control.matches(label, _command(ctx, domain="light", area="Salon", value=40.0), None)
    assert not control.matches(label, _command(ctx, domain="light", area="Kuchnia", value=40), None)
    assert not control.matches(label, _command(ctx, domain="light", area="Salon", value=50), None)
    assert not control.matches(label, None, None)
    device = control.Label("device_on_off", {"intent": "HassTurnOn", "domain": "light",
                                             "name": "lampka"}, "Lampa przy kanapie")  # fmt: skip
    command = _command(ctx, domain="light", name="lampka", area="Salon")
    assert control.matches(device, command, "Lampa przy kanapie")  # room in a device command
    assert not control.matches(device, command, "Kuchnia Światło")


def test_answer_fields_whole_numbers(ctx) -> None:
    fields = control.answer_fields(_command(ctx, domain="light", value=40.0))
    assert fields["value"] == 40 and isinstance(fields["value"], int)


def test_control_generation_keeps_only_checked_sentences(ctx) -> None:
    ctx.settings["generate"]["control"] = {"labels": 4, "sentences_per_label": 2}
    # the fake teacher parses everything as "turn on the kitchen light"
    parsed = {"intencja": "HassTurnOn", "domena": "light", "obszar": "Kuchnia"}
    ctx.teacher_obj = FakeTeacher(["Zapal światło w kuchni", "Zgaś lampkę w salonie"],
                                  parse=lambda content: parsed)  # fmt: skip
    control.generate(ctx)
    rows = list(read_jsonl(ctx.ws.generated / "control.jsonl"))
    rejected = list(read_jsonl(ctx.ws.generated / "control_rejected.jsonl"))
    assert rejected and all("plan" in r and "parsed" in r for r in rejected)
    for row in rows:
        assert row["text"] != "Zgaś lampkę w salonie"  # a test command
        assert json.loads(row["answer"])["obszar"] == "Kuchnia"


# --- answers ----------------------------------------------------------------------------------


def test_given_scenarios_have_checkable_facts(ctx) -> None:
    from datetime import datetime

    rng = ctx.rng("g")
    kinds = set()
    for _ in range(200):
        s = ctx.pack.given_scenario(rng, datetime(2026, 3, 4, 9, 5), ["Ola", "Kuba"])
        kinds.add(s["kind"])
        assert s["data"] and s["question"] and s["must"]
    assert kinds == {"sum", "tomorrow", "minutes", "lessons", "unknown", "car", "chores"}


def test_form_problems() -> None:
    assert answers.form_problems("Jutro masz basen o 17:00.", 1, 3) == []
    assert "markup" in answers.form_problems("**Jutro** basen.", 1, 3)
    assert "raw state" in answers.form_problems("Lampa jest unavailable.", 1, 3)
    assert answers.form_problems("A. B. C. D.", 1, 3) == ["too long: 4"]
    assert answers.form_problems("", 1, 3) == ["empty"]
    assert answers.form_problems("On jest w domu.", 1, 3) == []  # „on” is a pronoun


def test_given_answers_are_checked(ctx) -> None:
    ctx.settings["generate"]["answers"]["given"] = 3
    ctx.teacher_obj = FakeTeacher(text="Nie wiem.")
    out = ctx.ws.generated / "answers.jsonl"
    with answers.JsonlWriter(out, key=answers._key, group=lambda r: r["part"].split(":")[0]) as w:
        answers.given(ctx, w)
    for row in read_jsonl(out):  # only „I don't know” questions pass with this answer
        assert row["part"] == "given:unknown"
        assert row["messages"][0]["role"] == "system"


def test_data_topics_and_questions(ctx) -> None:
    assert [t.name for t in answers.data_topics(ctx)] == ["kalendarz", "pogoda"]
    out = ctx.ws.generated / "router.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"topic": "kalendarz", "source": "paraphrase", "text": "Co jest jutro?"},
            {"topic": "kalendarz", "source": "intent", "text": "x"},
            {"topic": "pogoda", "source": "paraphrase", "text": "Pada?"}]  # fmt: skip
    out.write_text("\n".join(json.dumps(r) for r in rows))
    assert answers.topic_questions(ctx, "kalendarz") == ["Co jest jutro?"]


# --- dataset --------------------------------------------------------------------------------


def _write(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def test_build_makes_integration_chats_without_test_sentences(ctx) -> None:
    ctx.settings["generate"]["router"].update(max_per_topic=50, min_per_topic=3, noise=0)
    _write(ctx.ws.generated / "router.jsonl", [
        {"role": "router", "part": "p", "text": "Co Tomek ma w piątek?", "topic": "kalendarz", "source": "paraphrase"},
        {"role": "router", "part": "p", "text": "Włącz światło w kuchni", "topic": "sterowanie", "source": "paraphrase"},
    ])  # fmt: skip
    answer = ctx.integ.control_answer(ctx.home, {"intent": "HassTurnOn", "domain": "light"})
    _write(ctx.ws.generated / "control.jsonl", [
        {"role": "control", "part": "control:x", "text": "Zapal wszystkie lampy", "answer": answer, "source": "teacher"},
    ])  # fmt: skip
    _write(ctx.ws.generated / "answers.jsonl", [
        {"role": "answers", "part": "given:sum", "id": "1", "text": "Ile mają razem?",
         "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "Ile mają razem?"}],
         "answer": "Razem 40 zł.", "source": "teacher"},
    ])  # fmt: skip
    folder = build.build(ctx, "t1")
    rows = [json.loads(line) for part in ("train", "dev")
            for line in (folder / f"{part}.jsonl").read_text().splitlines()]  # fmt: skip
    texts = {r["text"] for r in rows}
    assert not any(
        "swiatlo w kuchni" in t.lower().replace("ś", "s").replace("ł", "l") for t in texts
    )
    card = json.loads((folder / "card.json").read_text())
    assert card["holdout_rejected"] >= 1 and card["roles"]["control"] == 1
    for row in rows:
        assert row["messages"][-1]["role"] == "assistant"
        if row["role"] == "router":
            assert row["messages"][:2] == ctx.integ.router_messages(ctx.config, row["text"])


def test_dev_split_is_stable() -> None:
    texts = [f"Pytanie numer {i}" for i in range(2000)]
    dev = [t for t in texts if build.is_dev(t, 0.05)]
    assert dev == [t for t in texts if build.is_dev(t, 0.05)]
    assert 40 < len(dev) < 160


def test_router_rows_pad_small_topics(ctx) -> None:
    ctx.settings["generate"]["router"].update(max_per_topic=10, min_per_topic=6, noise=0)
    _write(ctx.ws.generated / "router.jsonl", [
        {"role": "router", "part": "p", "text": f"Pytanie o pogodę {i}", "topic": "pogoda", "source": "paraphrase"}
        for i in range(2)
    ])  # fmt: skip
    rows = build.router_rows(ctx, ctx.rng("b"))
    assert len(rows) == 6 and sum("+noise" in r["source"] for r in rows) == 4
