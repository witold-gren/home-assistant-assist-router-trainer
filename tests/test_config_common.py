"""Settings, workspace and the shared generator helpers."""

from __future__ import annotations

import json
from pathlib import Path
import random

import pytest
import yaml

from router_trainer.config import (
    Workspace,
    deep_merge,
    init_workspace,
    load_settings,
    model_settings,
    ollama_name,
)
from router_trainer.generate.common import (
    JsonlWriter,
    list_schema,
    noisy,
    read_jsonl,
    sentences_of,
    strip_speaker,
    tidy,
)


def test_deep_merge_keeps_defaults() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": [1]}
    merged = deep_merge(base, {"a": {"y": 3}, "b": [2]})
    assert merged == {"a": {"x": 1, "y": 3}, "b": [2]}
    assert base["a"]["y"] == 2  # not changed in place


def test_settings_fall_back_to_the_example(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    ws.config_file.write_text(yaml.safe_dump({"ollama": {"jetson": "http://j:1"}}))
    settings = load_settings(ws)
    assert settings["ollama"]["jetson"] == "http://j:1"
    assert settings["ollama"]["teacher"] == "gemma4:26b"  # from the example
    assert model_settings(settings, "e4b")["load_in_4bit"] is True
    with pytest.raises(ValueError, match="unknown model"):
        model_settings(settings, "e9b")


def test_init_keeps_an_existing_config(tmp_path) -> None:
    ws = init_workspace(tmp_path / "ws")
    ws.config_file.write_text("router_repo: /x\n")
    init_workspace(ws.root)
    assert ws.config_file.read_text() == "router_repo: /x\n"


def test_workspace_paths(tmp_path) -> None:
    ws = Workspace(tmp_path)
    assert ws.path("inputs/router.yaml") == tmp_path / "inputs" / "router.yaml"
    assert ws.path("/abs/file") == Path("/abs/file")
    assert ws.run("oct-e4b") == tmp_path / "runs" / "oct-e4b"


def test_ollama_name() -> None:
    settings = {"export": {"name": "assist-router-{model}-ft"}}
    assert ollama_name(settings, "e2b", "oct27-e2b") == "assist-router-e2b-ft:oct27-e2b"


def test_jsonl_writer_resumes_and_counts(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    with JsonlWriter(path) as writer:
        assert writer.write({"part": "p", "text": "Włącz światło"})
        assert not writer.write({"part": "p", "text": "wlacz swiatlo"})  # same after normalizing
        assert writer.write({"part": "q", "text": "Włącz światło"})
    with path.open("a") as handle:
        handle.write('{"part": "p", "text": "cut')  # a line cut by a stop
    with JsonlWriter(path) as writer:
        assert writer.count("p") == 1 and writer.count("q") == 1
        assert not writer.write({"part": "p", "text": "Włącz światło"})
    assert len(list(read_jsonl(path))) == 2


def test_jsonl_writer_groups(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    group = lambda row: row["part"].split(":")[0]  # noqa: E731
    with JsonlWriter(path, key=lambda r: r["id"], group=group) as writer:
        writer.write({"part": "live:kalendarz", "id": "1", "text": "a"})
        writer.write({"part": "live:pogoda", "id": "2", "text": "b"})
    with JsonlWriter(path, key=lambda r: r["id"], group=group) as writer:
        assert writer.count("live") == 2


def test_noise_and_tidy_are_reproducible() -> None:
    texts = [noisy("Jakie Ola ma jutro lekcje?", random.Random(i)) for i in range(40)]
    assert texts == [noisy("Jakie Ola ma jutro lekcje?", random.Random(i)) for i in range(40)]
    assert len(set(texts)) > 3
    assert tidy("  co   jest jutro", random.Random(1))[0] == "C"


def test_teacher_reply_sentences() -> None:
    assert list_schema("zdania")["required"] == ["zdania"]
    reply = {"zdania": ["Kuba: Zgaś światło", "", 5, "Włącz radio"]}
    assert sentences_of(reply, "zdania") == ["Zgaś światło", "Włącz radio"]
    assert sentences_of(None, "zdania") == []
    assert strip_speaker("Mama: co jest na obiad?") == "co jest na obiad?"
    assert json.dumps(list_schema("x"))


def test_accents_and_speakers_of_any_latin_language() -> None:
    from router_trainer.holdout import normalize, strip_accents

    assert strip_accents("Zażółć gęślą jaźń") == "Zazolc gesla jazn"
    assert strip_accents("Příliš žluťoučký kůň") == "Prilis zlutoucky kun"
    assert normalize("Øl, DOBRÝ den!") == "ol dobry den"
    assert strip_speaker("Ťapka: rozsviť světlo") == "rozsviť světlo"
    assert strip_speaker("Mum: turn on the light") == "turn on the light"
    assert strip_speaker("ok: turn on") == "ok: turn on"  # not a name
