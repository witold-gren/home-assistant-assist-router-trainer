"""Router labels checked with the router's own prompt, and sentences on the borders of topics."""

from __future__ import annotations

import json

from router_trainer.generate import labels, router
from router_trainer.generate.common import read_jsonl
from tests.conftest import needs_router

pytestmark = needs_router


class LabelTeacher:
    """The topic of a sentence from a fixed rule; contrast replies from a list per call."""

    def __init__(self, sentences=None, contrast=None) -> None:
        self.sentences = sentences or []
        self.contrast = list(contrast or [])
        self.asked: list[str] = []
        self.prompts: list[str] = []

    def json(self, messages, schema, **_):
        content = messages[-1]["content"]
        key = next(iter(schema["properties"]))
        if key == "temat":
            self.asked.append(content)
            lower = content.lower()
            if lower.startswith(("włącz", "puść", "zgaś")):
                return {"temat": "sterowanie"}
            if "pogod" in lower or "pada" in lower:
                return {"temat": "pogoda"}
            if "?" in content and "kalendarz" in lower:
                return {"temat": "kalendarz"}
            return {"temat": "inne"} if "kawał" in lower else {"temat": None}
        self.prompts.append(content)
        if key == "zdania":
            return {key: list(self.sentences)}
        if key == "temat_a":
            return self.contrast.pop(0) if self.contrast else {"temat_a": [], "temat_b": []}
        return None


def _rows(ctx, rows) -> None:
    path = ctx.ws.generated / "router.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _row(text, topic, source, **extra):
    return {"role": "router", "part": f"{source}:{topic}", "text": text, "topic": topic,
            "source": source, **extra}  # fmt: skip


def test_sentences_the_router_puts_elsewhere_are_dropped(ctx) -> None:
    ctx.teacher_obj = LabelTeacher()
    _rows(ctx, [
        _row("Puść podcast w kuchni", "pogoda", "paraphrase"),  # a command - sterowanie
        _row("Czy jutro będzie padać?", "pogoda", "paraphrase"),
        _row("Opowiedz coś miłego", "inne", "paraphrase"),  # no clear answer - kept
        _row("Pusc podcast w kuchni", "pogoda", "asr", spoken="Puść podcast w kuchni"),
        _row("Puść podcast w kuchni", "sterowanie", "trigger"),  # automations are not checked
    ])  # fmt: skip
    checker = labels.Checker(ctx)
    assert labels.clean(ctx, checker) == 2
    kept = [(r["text"], r["source"]) for r in read_jsonl(ctx.ws.generated / "router.jsonl")]
    assert kept == [
        ("Czy jutro będzie padać?", "paraphrase"),
        ("Opowiedz coś miłego", "paraphrase"),
        ("Puść podcast w kuchni", "trigger"),
    ]
    dropped = read_jsonl(ctx.ws.generated / "labels_dropped.jsonl")
    assert [(r["text"], r["teacher"]) for r in dropped] == [("Puść podcast w kuchni", "sterowanie")]
    # the answers are kept: a second run asks nothing
    asked = len(ctx.teacher_obj.asked)
    assert labels.clean(ctx, labels.Checker(ctx)) == 0
    assert len(ctx.teacher_obj.asked) == asked


def test_the_check_can_be_switched_off(ctx) -> None:
    ctx.settings["generate"]["router"]["check_labels"] = False
    assert labels.checked_sources(ctx) == ()
    ctx.settings["generate"]["router"]["check_labels"] = ["log"]
    assert labels.checked_sources(ctx) == ("log",)
    ctx.settings["generate"]["router"]["check_labels"] = True
    assert labels.checked_sources(ctx) == ("paraphrase", "contrast", "external")


def test_new_paraphrases_need_the_same_topic(ctx) -> None:
    ctx.settings["generate"]["router"]["paraphrases_per_topic"] = 1
    ctx.teacher_obj = LabelTeacher(["Puść radio", "Czy będzie padać w sobotę?"])
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        router.paraphrases(ctx, writer, ctx.holdout(), ctx.home, labels.Checker(ctx))
    by_topic = {(r["topic"], r["text"]) for r in read_jsonl(out)}
    assert ("pogoda", "Czy będzie padać w sobotę?") in by_topic
    assert ("sterowanie", "Puść radio") in by_topic
    assert ("pogoda", "Puść radio") not in by_topic
    assert ("kalendarz", "Puść radio") not in by_topic


def _eval(ctx, name, errors) -> None:
    folder = ctx.ws.runs / name
    folder.mkdir(parents=True)
    (folder / "eval.json").write_text(json.dumps({"m": {"router": {"errors": errors}}}), "utf-8")


def test_confused_pairs_come_from_the_evaluations(ctx) -> None:
    _eval(ctx, "a", [
        "Puść muzykę w kuchni -> pogoda (expected sterowanie)",
        "Włącz radio -> pogoda (expected sterowanie)",
        "Zrób mi kamerę. -> kalendarz (expected inne / niezrozumiale)",
        "not an error line",
    ])  # fmt: skip
    _eval(ctx, "b", ["Co mamy jutro? -> inne (expected kalendarz)"])
    (ctx.ws.runs / "broken").mkdir()
    (ctx.ws.runs / "broken" / "eval.json").write_text("{", "utf-8")
    assert labels.confusions(ctx.ws.runs)[0] == ("pogoda", "sterowanie")
    pairs = labels.contrast_pairs(ctx)
    assert pairs[0] == ("pogoda", "sterowanie")
    assert set(pairs) == {
        ("pogoda", "sterowanie"),
        ("inne", "kalendarz"),
        ("kalendarz", "niezrozumiale"),
    }
    ctx.settings["generate"]["router"]["contrast"] = {"pairs": [["sterowanie", "pogoda"],
                                                                ["pogoda", "brak"]]}  # fmt: skip
    assert labels.contrast_pairs(ctx) == [("pogoda", "sterowanie")]  # unknown topics left out


def test_extra_contrast_pairs_join_the_automatic_ones(ctx) -> None:
    _eval(ctx, "a", ["Włącz radio -> pogoda (expected sterowanie)"])
    ctx.settings["generate"]["router"]["contrast"] = {
        "pairs": "auto",
        "extra": [["kalendarz", "inne"], ["pogoda", "sterowanie"], ["inne", "brak"]],
    }
    # extra first, duplicates and unknown topics left out
    assert labels.contrast_pairs(ctx) == [("inne", "kalendarz"), ("pogoda", "sterowanie")]


def test_border_sentences_keep_only_clear_ones(ctx) -> None:
    ctx.settings["generate"]["router"]["contrast"] = {
        "per_side": 2,
        "pairs": [["sterowanie", "pogoda"]],
    }
    ctx.teacher_obj = LabelTeacher(contrast=[
        {   # pogoda is a, sterowanie b (sorted)
            "temat_a": ["Czy będzie padać w ogrodzie?", "Włącz prognozę"],  # 2nd is a command
            "temat_b": ["Włącz ogrzewanie w kuchni", "Włącz światło w kuchni"],  # 2nd is a test
        },
        {"temat_a": ["Jaka pogoda w sobotę?"], "temat_b": ["Zgaś lampkę w ogrodzie"]},
    ])  # fmt: skip
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        labels.contrast(ctx, writer, ctx.holdout(), labels.Checker(ctx), ctx.home)
    rows = {(r["topic"], r["text"]) for r in read_jsonl(out)}
    assert rows == {
        ("pogoda", "Czy będzie padać w ogrodzie?"),
        ("pogoda", "Jaka pogoda w sobotę?"),
        ("sterowanie", "Włącz ogrzewanie w kuchni"),
        ("sterowanie", "Zgaś lampkę w ogrodzie"),
    }
    prompt = ctx.teacher_obj.prompts[0]
    assert "A) pogoda" in prompt and "B) sterowanie" in prompt and "temat_a" in prompt


def test_contrast_is_off_without_pairs(ctx) -> None:
    ctx.teacher_obj = LabelTeacher()
    out = ctx.ws.generated / "router.jsonl"
    with router.JsonlWriter(out) as writer:
        labels.contrast(ctx, writer, ctx.holdout(), labels.Checker(ctx), ctx.home)  # no runs yet
    assert ctx.teacher_obj.prompts == []
