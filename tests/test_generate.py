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


def test_a_value_set_outright_is_no_change(ctx) -> None:
    """„Ustaw na 22 stopnie” reads back as change „ustaw”; the plan has no change - the same."""
    label = control.Label("climate", {"intent": "HassTurnOn", "domain": "climate",
                                      "area": "Salon", "value": 22})  # fmt: skip
    set_word = ctx.integ.lang.CHANGE_SET
    command = _command(ctx, domain="climate", area="Salon", value=22, change=set_word)
    assert control.matches(label, command, None, set_word)
    assert not control.matches(label, command, None)  # without the word it would be refused
    more = _command(
        ctx, domain="climate", area="Salon", value=22, change=ctx.integ.lang.CHANGE_MORE
    )
    assert not control.matches(label, more, None, set_word)


def test_the_planned_device_counts_under_another_domain(ctx) -> None:
    """A switch and a script of the same name: the device found is the one planned."""
    label = control.Label("device_on_off", {"intent": "HassTurnOn", "domain": "switch",
                                            "name": "Robot"}, "Robot")  # fmt: skip
    command = _command(ctx, domain="script", name="Robot")
    assert control.matches(label, command, "Robot")
    assert not control.matches(label, command, "Lampa przy kanapie")


def test_numbers_are_given_as_people_say_them() -> None:
    assert control.spoken_number(22.0) == 22 and control.spoken_number(22.5) == "22,5"
    assert control.spoken_number(40) == 40 and control.spoken_number("Salon") == "Salon"


def test_requests_side_by_side_keep_the_order() -> None:
    import threading
    import time

    from router_trainer.generate.common import in_parallel

    threads = set()

    def slow(n):
        threads.add(threading.get_ident())
        time.sleep(0.05 * (5 - n))  # the first finishes last
        return n * 10

    assert in_parallel(slow, [1, 2, 3, 4], 2) == [10, 20, 30, 40]
    assert len(threads) == 2
    assert in_parallel(lambda n: n + 1, [1, 2], 1) == [2, 3]


def test_the_teacher_uses_one_context_and_a_fast_ollama(monkeypatch) -> None:
    """Ollama reloads the model when num_ctx changes - every call uses the same one."""
    from router_trainer import teacher as teacher_module

    sent = []
    monkeypatch.setattr(teacher_module, "http", lambda url, path, body=None, **kw:
                        sent.append(body) or {"message": {"content": '{"a": 1}'}})  # fmt: skip
    teacher = teacher_module.Teacher("http://x", "gemma4:26b")
    teacher.json([{"role": "user", "content": "a"}], {}, num_predict=30)
    teacher.text([{"role": "user", "content": "b"}])
    assert {body["options"]["num_ctx"] for body in sent} == {teacher_module.NUM_CTX}
    monkeypatch.delenv("OLLAMA_NUM_PARALLEL", raising=False)
    env = teacher_module.ollama_env("127.0.0.1:11535", teacher_module.OLLAMA_DIR)
    assert env["OLLAMA_NUM_PARALLEL"] == str(teacher_module.PARALLEL)
    assert env["OLLAMA_FLASH_ATTENTION"] == "1" and env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"


def test_a_router_only_dataset_leaves_commands_and_answers_out(ctx) -> None:
    from router_trainer.generate.common import JsonlWriter

    with JsonlWriter(ctx.ws.generated / "router.jsonl") as writer:
        for i in range(30):
            writer.write(
                {
                    "role": "router",
                    "part": "paraphrase",
                    "text": f"Pytanie numer {i}",
                    "topic": "inne",
                    "source": "paraphrase",
                }
            )
    with JsonlWriter(ctx.ws.generated / "control.jsonl") as writer:
        writer.write(
            {
                "role": "control",
                "part": "control:x",
                "label": 0,
                "text": "Zapal lampę",
                "answer": "{}",
                "source": "teacher",
            }
        )
    path = build.build(ctx, "only-router", ("router",))
    roles = {
        json.loads(line)["role"]
        for f in path.glob("*.jsonl")
        for line in f.read_text().splitlines()
        if line.strip()
    }
    assert roles == {"router"}


def test_titles_come_from_the_wikipedia_of_the_language(tmp_path, monkeypatch) -> None:
    import io

    asked = []

    def urlopen(request, timeout):
        asked.append(request.full_url)
        pages = [{"title": "Prague"}, {"title": "Vltava (river)"}]
        return io.BytesIO(json.dumps({"query": {"random": pages}}).encode())

    monkeypatch.setattr(router.urllib.request, "urlopen", urlopen)
    titles = router.wikipedia_titles(tmp_path / "t.json", 2, set(), "cs")
    assert titles == ["Prague", "Vltava"]
    assert asked[0].startswith("https://cs.wikipedia.org/")


def test_triggers_are_read_in_the_router_language() -> None:
    triggers = [{"key": "a#0", "id": "a", "templates": ["turn on the {thing}"]}]
    commands = {"lights": {"turn on the lamp"}}
    assert router.map_triggers(triggers, commands, {}, "en") == {"a#0": "lights"}


def test_the_trigger_report_says_where_each_trigger_goes(ctx) -> None:
    config = ctx.input("ha_config")
    config.mkdir(parents=True)
    (config / "automations.yaml").write_text(
        "- id: alarm\n  alias: Alarm\n  triggers:\n"
        "  - trigger: conversation\n    command: ['czy alarm jest włączony']\n"
        "  - trigger: conversation\n    command: ['włącz alarm']\n"
        "- id: kawa\n  alias: Kawa\n  triggers:\n"
        "  - trigger: conversation\n    command: ['zrób kawę']\n"
        "- id: nowe\n  alias: Nowe\n  triggers:\n"
        "  - trigger: conversation\n    command: ['coś nowego']\n",
        encoding="utf-8",
    )
    ctx.settings["topic_overrides"] = {"alarm": "inne", "alarm#1": "sterowanie", "kawa": "brak"}
    (ctx.ws.generated).mkdir(parents=True, exist_ok=True)
    (ctx.ws.generated / "trigger_topics.json").write_text(
        json.dumps({"nowe#0": {"topic": "pogoda"}}), encoding="utf-8"
    )
    rows = {r["key"]: (r["topic"], r["how"], r["known_topic"]) for r in router.trigger_report(ctx)}
    assert rows == {
        "alarm#0": ("inne", "override", True),  # the whole automation
        "alarm#1": ("sterowanie", "override", True),  # one trigger of it
        "kawa#0": ("brak", "override", False),  # a topic router.yaml does not have
        "nowe#0": ("pogoda", "teacher", True),
    }


def test_raw_states_depend_on_the_language() -> None:
    assert answers.form_problems("On jest w domu.", 1, 3) == []  # Polish: „on” is „he”
    assert "raw state" in answers.form_problems("The lamp is on.", 1, 3, ())


def test_custom_sentences_of_home_assistant_become_router_examples(ctx) -> None:
    folder = ctx.input("ha_config") / "custom_sentences" / "pl"
    folder.mkdir(parents=True)
    (folder / "dom.yaml").write_text(
        "language: pl\nintents:\n"
        "  HassTurnOn:\n    data:\n      - sentences: ['odpal {name}']\n"
        "  KawaIntent:\n    data:\n      - sentences: ['zrób (mi|nam) kawę [{rodzaj}]']\n"
        "  PogodaDzialka:\n    data:\n      - sentences: ['jaka pogoda na działce']\n"
        "lists:\n  rodzaj:\n    values: [espresso, latte]\n",
        encoding="utf-8",
    )
    (folder / "broken.yaml").write_text("intents: [", encoding="utf-8")
    ctx.settings["intent_topics"] = {"PogodaDzialka": "pogoda"}
    ctx.settings["generate"]["router"]["per_template"] = 5
    asked = []

    def classify(texts):
        asked.append(texts)
        return "inne"

    rows = router.custom_sentences(ctx, ctx.home, ctx.rng("c"), classify)
    topics = {topic for text, topic, source in rows if source == "custom"}
    by_text = {text: topic for text, topic, _ in rows}
    assert topics == {"sterowanie", "inne", "pogoda"}
    assert by_text["jaka pogoda na działce"] == "pogoda"
    assert any(t.startswith("odpal ") and len(t) > 6 for t in by_text)  # a device of the home
    assert any(t.startswith("zrób") for t in by_text if by_text[t] == "inne")
    assert len(asked) == 1  # only the home's own intent
    cache = json.loads((ctx.ws.generated / "trigger_topics.json").read_text(encoding="utf-8"))
    assert cache["intent:KawaIntent"]["topic"] == "inne"
    rows = router.custom_sentences(ctx, ctx.home, ctx.rng("c"), classify)  # saved: not asked again
    assert len(asked) == 1


def test_no_custom_sentences_no_rows(ctx) -> None:
    assert router.custom_sentences(ctx, ctx.home, ctx.rng("c")) == []
