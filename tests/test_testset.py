"""The generated test: facts, the active test with its review, the generator with fake models."""

from __future__ import annotations

import json
import re

import pytest
import yaml

from router_trainer.config import init_workspace
from router_trainer.testset import facts, store
from tests.conftest import needs_router

# --- facts -----------------------------------------------------------------------------------


def test_fact_patterns_accept_spoken_forms() -> None:
    assert facts.pattern("17:00") == r"\b0?17[:.,]00\b"
    assert re.search(facts.pattern("7:30"), "zaczyna o 07:30") and re.search(
        facts.pattern("7:30"), "o 7.30"
    )
    assert re.search(facts.pattern("8.05"), "o 8:05 masz") is not None
    assert re.search(facts.pattern("205"), "razem 205 zł")
    assert not re.search(facts.pattern("205"), "razem 2050 zł")
    assert facts.pattern("wizyta u dentysty") == "denty"
    assert re.search(facts.pattern("basen"), "jutro na basenie")
    assert facts.pattern("  ") is None


def test_facts_must_be_in_the_source() -> None:
    data = "Kalendarz - Ola: wtorek 4.03 - 17:00 basen; środa - 18:30 tańce."
    assert facts.to_patterns(["17:00", "basen", "kino", "18:30"], data, limit=2) == [
        r"\b0?17[:.,]00\b",
        r"\b0?18[:.,]30\b",
    ]  # fmt: skip
    assert facts.to_patterns(["kino"], data) == []
    # at least one of several facts (a broad question has several right answers)
    assert facts.required(["a", "b"]) == [["a", "b"]] and facts.required(["a"]) == ["a"]
    assert facts.required([]) == []
    # attribute names of the data, lone digits; big numbers with a space
    bank = "Konto Ola: 20 zł (savings: 15, debt: 0), lekcja 1, przebieg 156317 km"
    assert facts.to_patterns(["savings", "debt", "1", "156317"], bank) == [r"\b156\s?317\b"]
    assert re.search(facts.pattern("156317"), "przejechało 156 317 kilometrów")
    assert re.search(facts.pattern("156317 km"), "przejechało 156 317 kilometrów")
    assert facts.pattern("2026 r.") is None and facts.pattern("5.96") == r"5[.,]96"
    assert not facts.TIME.match("24:10") and not facts.TIME.match("5.96")
    # raw HA states are translated in answers; a date may name the year
    weather = "Pogoda: sunny, 12.5 °C, wtorek 4.03.2026"
    assert facts.to_patterns(["sunny", "12.5"], weather) == [r"12[.,]5"]
    assert facts.to_patterns(["2026.", "12.5"], weather, forbidden=True) == [r"12[.,]5"]
    # facts the question already says, generic words; facts with digits first
    data = "Łazienka: wilgotność 51 %, temperatura 22 °C, roku 2026"
    question = "Ile wilgotności jest w łazience?"
    assert facts.to_patterns(["wilgotność", "roku", "51"], data, question=question,
                             generic=frozenset({"roku"})) == [r"\b51\b"]  # fmt: skip


# --- the active test and its review ------------------------------------------------------------------

TESTS = {
    "router": [["Co jest jutro?", "kalendarz"], ["Zgaś światło", "sterowanie"]],
    "control": {"cases": [{"text": "Zgaś lampkę", "expect": {"intent": "HassTurnOff"}}]},
    "real": {
        "cases": [{"name": "r1", "topic": "kalendarz", "question": "Co jutro?", "must": ["basen"]}]
    },
}


def _generated(ws, name: str) -> None:
    folder = store.test_dir(ws, name)
    folder.mkdir(parents=True)
    (folder / store.TEST_FILE).write_text(yaml.safe_dump(TESTS, allow_unicode=True))
    (folder / store.DATA_FILE).write_text("live: {}\n")
    (folder / store.CARD_FILE).write_text(json.dumps({"created": "x", "dropped": {"a": 2}}))


def test_active_test_and_review(tmp_path) -> None:
    from router_trainer.config import load_settings

    ws = init_workspace(tmp_path / "ws")
    settings = load_settings(ws)
    assert store.active(ws) == "ha"
    with pytest.raises(ValueError):
        store.set_active(ws, "nope")
    _generated(ws, "t1")
    store.set_active(ws, "t1")
    assert store.paths(ws, settings)[1].name == store.DATA_FILE
    assert len(store.load(ws, settings)["router"]) == 2
    store.set_rejected(ws, "t1", "router:co jest jutro", True)
    store.set_rejected(ws, "t1", "real:r1", True)
    tests = store.load(ws, settings)
    assert tests["router"] == [["Zgaś światło", "sterowanie"]] and tests["real"]["cases"] == []
    listing = store.listing(ws, settings)
    assert listing["active"] == "t1" and listing["tests"][0]["rejected"] == 2
    cases = store.review_list(ws, settings, "t1")
    assert {c["id"] for c in cases if c["rejected"]} == {"router:co jest jutro", "real:r1"}
    assert "intent=HassTurnOff" in next(c["expect"] for c in cases if c["section"] == "control")
    store.set_rejected(ws, "t1", "real:r1", False)
    assert len(store.load(ws, settings)["real"]["cases"]) == 1


def test_the_ha_test_file_is_the_default(tmp_path) -> None:
    from router_trainer.config import load_settings

    ws = init_workspace(tmp_path / "ws")
    settings = load_settings(ws)
    with pytest.raises(FileNotFoundError):
        store.load(ws, settings)
    ha_file = ws.path(settings["inputs"]["tests"])
    ha_file.parent.mkdir(parents=True)
    ha_file.write_text(yaml.safe_dump(TESTS, allow_unicode=True))
    store.set_rejected(ws, "ha", "control:zgas lampke", True)
    assert store.load(ws, settings)["control"]["cases"] == []
    assert ha_file.read_text() == yaml.safe_dump(TESTS, allow_unicode=True)  # file untouched


# --- the generator, with fake models, HA and Wikipedia ----------------------------------------------


class FakeModel:
    """The writer and the judge: fixed rules instead of a model."""

    calls = 0

    def __init__(self, url: str = "", model: str = "") -> None:
        self.model = model

    def ensure(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def json(self, messages, schema, **_):
        content = messages[-1]["content"]
        key = next(iter(schema["properties"]))
        if key == "temat":
            if "Kopernik" in content or "kawał" in content:
                # the two models disagree about one log question
                return {"temat": "wiedza" if "judge" in self.model else "inne"}
            for topic in ("kalendarz", "pogoda", "wiedza", "sterowanie"):
                if topic in content.lower():
                    return {"temat": topic}
            return {"temat": "inne"}
        if key in ("zdania", "pytania"):
            match = re.search(r"na temat: (\w+)", content)
            topic = match.group(1) if match else "wiedza"
            FakeModel.calls += 1  # every call writes other sentences
            return {key: [f"Pytanie {FakeModel.calls}.{i} o {topic}" for i in range(4)]}
        if key == "fakty":
            return {"fakty": ["17:00", "basen", "nie ma tego"], "bledne": ["18:30"]}
        # the command parser: always "start the vacuum"
        return {"intencja": "HassVacuumStart", "domena": "vacuum"}


@needs_router
def test_generator_writes_a_benchmark_test(ctx, monkeypatch) -> None:
    from router_trainer.testset import build

    ctx.settings["ollama"]["test_writer"] = "writer"
    ctx.settings["ollama"]["teacher"] = "judge"
    ctx.settings["test"].update(router_per_topic=2, control=3, answers=2, real_per_topic=1,
                                real_max=2, wikipedia=1)  # fmt: skip
    ctx.teacher_obj = FakeModel(model="judge")
    ctx.token = lambda: "t"
    monkeypatch.setattr(build, "start_local", lambda settings, root: "http://x")
    monkeypatch.setattr(build, "Teacher", FakeModel)
    monkeypatch.setattr(build.teacher_module, "make",
                        lambda settings, root, role: FakeModel(model=settings["ollama"][role]))  # fmt: skip
    vacuum = build.control_gen.Label("vacuum", {"intent": "HassVacuumStart", "domain": "vacuum"})
    monkeypatch.setattr(build.control_gen, "plan", lambda ctx, home, rng: vacuum)
    monkeypatch.setattr(ctx.integ.snapshot_data, "home", lambda url, token: ctx.home)
    data = "Kalendarz - Ola: wtorek - 17:00 basen; środa - 18:30 tańce."
    monkeypatch.setattr(ctx.integ.topic_data, "load_home", lambda ha: object())
    monkeypatch.setattr(ctx.integ.topic_data, "topic_data",
                        lambda home, config, topic, q, speaker, now: {
                            "data": data, "hint": "", "speaker": None, "people": [], "when": None})  # fmt: skip
    article = "Bardzo długi artykuł o basenie, otwartym o 17:00. " * 20
    monkeypatch.setattr(ctx.integ.snapshot_data, "wikipedia", lambda q, lang: ("Basen", article))
    # the training pool is empty, the test pool has one title
    monkeypatch.setattr(build.router_gen, "wikipedia_titles",
                        lambda cache, count, exclude, language="pl": [] if cache.name == "wiki_titles.json" else ["Basen"] * 3)  # fmt: skip
    log = ctx.ws.path("inputs/unrecognized_commands.csv")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("﻿timestamp;area;device;kind;text;response;route;speaker\n"
                   "1;;;x;Jaka jutro pogoda?;;;\n2;;;x;Opowiedz kawał o Koperniku;;;\n"
                   "3;;;x;Włącz światło w kuchni;;;\n", encoding="utf-8")  # fmt: skip

    folder = build.build(ctx, "auto1")
    tests = yaml.safe_load((folder / store.TEST_FILE).read_text())
    assert (folder / store.TEST_FILE).read_text().startswith("# Generated test (auto1")
    assert store.active(ctx.ws) == "auto1"
    router_cases = dict((q, t) for q, t in tests["router"])
    assert router_cases.get("Jaka jutro pogoda?") == "pogoda"  # a real question, both agree
    assert "Opowiedz kawał o Koperniku" not in router_cases  # the models disagreed
    assert all(t in ctx.config.topics for t in router_cases.values())
    assert tests["control"]["cases"] and all(
        c["expect"] == {"intent": "HassVacuumStart", "domain": "vacuum"}
        for c in tests["control"]["cases"]
    )
    assert (
        len(tests["answers"]["cases"]) == 2 and ctx.config.household in tests["answers"]["system"]
    )
    real = tests["real"]["cases"]
    assert real and real[0]["must"] == [[r"\b0?17[:.,]00\b", "basen"]] and real[0]["never"] == []
    snapshot = yaml.safe_load((folder / store.DATA_FILE).read_text())
    assert snapshot["live"][real[0]["name"]]["data"] == data and snapshot["home"] == ctx.home
    wiki = tests["wiki_answers"]["cases"]
    assert wiki and snapshot["wiki"][wiki[0]["source"]]["text"] == article
    card = json.loads((folder / store.CARD_FILE).read_text())
    assert card["dropped"]["router: models disagree"] >= 1
    # the benchmark reads it: a good answer passes the generated check
    assert ctx.integ.benchmark.check("Ola ma basen o 17:00.", real[0], 1, 3) == []
    assert ctx.integ.benchmark.check("Ola ma tańce o 18:30.", real[0], 1, 3)  # no basen at 17:00


@needs_router
def test_slot_values_suggested_once_and_saved(ctx) -> None:
    from router_trainer.generate import router

    asked = []

    def propose(name, templates):
        asked.append(name)
        return ["Ola", "Kuba", ""]

    triggers = [
        {"key": "a#0", "id": "a", "alias": "", "templates": ["co ma {dziecko} jutro", "a {kto}"]}
    ]
    ctx.settings["slot_values"] = {"kto": ["mama"]}
    values = router.auto_slot_values(ctx, triggers, propose)
    assert values == {"kto": ["mama"], "dziecko": ["Ola", "Kuba"]}
    assert router.auto_slot_values(ctx, triggers, propose)["dziecko"] == ["Ola", "Kuba"]
    assert asked == ["dziecko"]  # the saved suggestion is reused
    assert json.loads((ctx.ws.generated / "slot_values.json").read_text()) == {
        "dziecko": ["Ola", "Kuba"]
    }


def test_fact_patterns_take_the_language_rules() -> None:
    assert facts.pattern("pokój") == "pokój"  # no swaps without a language pack
    assert facts.pattern("pokój", 5, {"ó": "[óo]", "o": "[oó]"}) == "p[oó]k[óo]j"
    assert facts.pattern("swimming", 4) == "swim"
