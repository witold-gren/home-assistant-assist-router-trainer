"""A new language: the translated draft of both packs, checked, with REVIEW.md."""

from __future__ import annotations

import json
import re

import pytest
import yaml

from router_trainer import cli, language_tool, teacher as teacher_module
from router_trainer.config import init_workspace, load_settings, router_repo
from tests.conftest import needs_router

pytestmark = needs_router


class Translating:
    """Pretends to translate: texts get „ (cs)”, words and patterns come back as they were - except
    the few it breaks on purpose."""

    model = "fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def json(self, messages, schema, **_):
        prompt = messages[-1]["content"]
        self.prompts.append(messages[0]["content"] + prompt)
        props = schema["properties"]
        if "translations" in props:
            data = json.loads(
                prompt[prompt.index("\n") + 1 :]
                if prompt.startswith("Translate the values")
                else prompt[prompt.rindex("\n") + 1 :]
            )
            if isinstance(data, list):
                return {"translations": {text: f"{text} (cs)" for text in data}}
            out = {}
            for name, value in data.items():
                if name.endswith("_KEY"):
                    out[name] = value
                elif name == "MORE_ITEMS":
                    out[name] = "a další"  # the {count} lost: kept Polish, in REVIEW
                else:
                    out[name] = f"{value} (cs)"
            return {"translations": out}
        if "yaml" in props:
            body = prompt[
                prompt.index("\n", prompt.index("YAML value") if "YAML value" in prompt else 0)
                + 1 :
            ]
            if "(YES_WORDS)" in prompt:
                return {"yaml": "!tuple [ano, jo]"}
            if "(INTENTS)" in prompt:
                return {"yaml": "{ZapniIntent: !tuple [a, b]}"}  # an HA name translated: refused
            if "topic of the assistant's router" in prompt:
                part = yaml.safe_load(prompt[prompt.index("\n") + 1 :])
                return {
                    "yaml": yaml.safe_dump(
                        {**part, "examples": [e + " (cs)" for e in part["examples"]]}
                    )
                }
            text = prompt.split("\n")
            return {
                "yaml": "\n".join(
                    text[
                        text.index(next(t for t in text if t.startswith("codes) and numbers")))
                        + 1 :
                    ]
                )
                if any(t.startswith("codes) and numbers") for t in text)
                else body
            }
        if "pattern" in props:
            label = re.search(r"\((\w+(?:\[\d+\])?)\)", prompt)[1]
            if label == "ALARM_WORDS":
                return {"pattern": r"\bpoplach", "matches": ["zapni alarm"], "not_matches": []}
            return {}  # no answer: the Polish pattern stays, with a REVIEW line
        return None

    def text(self, messages, **_):
        return ""


@pytest.fixture
def ws(tmp_path):
    workspace = init_workspace(tmp_path / "ws")
    test = {"router": [["Włącz światło w kuchni", "sterowanie"], ["Co jest jutro?", "kalendarz"]],
            "control": {"cases": [{"text": "Zgaś lampkę", "expect": {"intent": "HassTurnOff"}}]},
            "answers": {"cases": [{"name": "a", "question": "Ile?", "must": ["\\d+"]}]}}  # fmt: skip
    path = workspace.path(load_settings(workspace)["inputs"]["tests"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(test, allow_unicode=True), encoding="utf-8")
    return workspace


def test_a_draft_of_a_new_language(ws, monkeypatch) -> None:
    fake = Translating()
    monkeypatch.setattr(teacher_module, "make", lambda settings, root, role: fake)
    repo = router_repo(load_settings(ws))
    result = language_tool.new(ws, "cs", repo)
    out = ws.root / "languages" / "cs"
    assert result["folder"] == str(out) and result["pending"] == 0
    assert not (repo / "custom_components" / "assist_router" / "languages" / "cs").exists()
    texts = yaml.safe_load(
        (out / "router" / "texts.yaml").read_text(encoding="utf-8").replace("!tuple", "")
    )
    assert texts["CODE"] == "cs" and texts["NO_PRINTS"].endswith("(cs)")
    assert texts["MORE_ITEMS"] == "… i {count} więcej"  # the translation lost {count}
    assert "Czech" in fake.prompts[0] and "Reference - Home Assistant" in fake.prompts[0]
    words = (out / "router" / "words.yaml").read_text(encoding="utf-8")
    assert "YES_WORDS: !tuple [ano, jo]" in words and "HassTurnOn" in words
    review = (out / "REVIEW.md").read_text(encoding="utf-8")
    assert "router/texts.yaml MORE_ITEMS: the {fields} changed" in review
    assert "router/words.yaml INTENTS: keys changed" in review
    assert "router/patterns.yaml ALARM_WORDS: the pattern does not find its examples" in review
    assert "router/grammar.py: always read by a speaker" in review
    assert "custom_components/assist_router/languages/cs/" in review
    grammar = (out / "router" / "grammar.py").read_text(encoding="utf-8")
    assert grammar.startswith("# REVIEW (Czech)") and " (cs)" in grammar
    example = yaml.safe_load((out / "router.example.yaml").read_text(encoding="utf-8"))
    assert example["language"] == "cs" and all(
        e.endswith("(cs)") for t in example["topics"].values() for e in t.get("examples", [])
    )
    test = yaml.safe_load((out / "model_test.yaml").read_text(encoding="utf-8"))
    assert test["router"][0] == ["Włącz światło w kuchni (cs)", "sterowanie"]
    assert test["control"]["cases"][0]["text"] == "Zgaś lampkę (cs)" and "answers" not in test
    found = language_tool.check(ws, "cs", repo)
    assert found["trainer"] == [], found["trainer"]
    assert found["router"] == [], found["router"]  # what failed kept the Polish value


def test_a_manual_writer_translates_by_hand(ws, monkeypatch, capsys) -> None:
    settings_file = ws.config_file
    settings_file.write_text(settings_file.read_text(encoding="utf-8")
                             + "\nteacher:\n  writer: {provider: manual}\n", encoding="utf-8")  # fmt: skip
    repo = router_repo(load_settings(ws))
    result = language_tool.new(ws, "cs", repo)
    tasks = [json.loads(line) for line in (ws.root / "languages" / "cs" / "tasks.jsonl").open()]
    assert result["pending"] == len(tasks) > 10
    fake = Translating()
    answers = ws.root / "answers.jsonl"
    with answers.open("w", encoding="utf-8") as handle:
        for task in tasks:
            reply = fake.json(task["messages"], task["schema"]) or {}
            handle.write(json.dumps({"id": task["id"], **reply}, ensure_ascii=False) + "\n")
    again = language_tool.new(ws, "cs", repo, answers=answers)
    assert again["pending"] == 0
    texts = (ws.root / "languages" / "cs" / "trainer" / "texts.yaml").read_text(encoding="utf-8")
    assert "(cs)" in texts
    assert (
        cli.main(
            ["--workspace", str(ws.root), "language", "check", "cs", "--router-repo", str(repo)]
        )
        == 0
    )
    assert "router: ready" in capsys.readouterr().out


def test_the_code_must_be_a_language(ws) -> None:
    repo = router_repo(load_settings(ws))
    with pytest.raises(ValueError, match="language code"):
        language_tool.new(ws, "Czech!", repo)
    with pytest.raises(ValueError, match="reference"):
        language_tool.new(ws, "pl", repo)


def test_string_literals_of_grammar() -> None:
    source = 'def f(n):\n    """Doc."""\n    x = {"HassTurnOn": "włączyć"}\n    return f"Ustawiono {n} urządzeń" if n else "nic"\n'
    assert language_tool.string_literals(source) == ["włączyć", "Ustawiono ", " urządzeń"]
