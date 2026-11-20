"""A draft of a new language: both language packs, an example router.yaml and the test, translated
from Polish by the writer teacher - then checked, with what needs a speaker's eye in REVIEW.md.

    router-trainer language new cs [--home] [--answers FILE]
    router-trainer language check cs

The draft goes to ``workspace/languages/<code>/`` and never into the repositories:

- ``router/`` - Assist Router's pack (texts.yaml, words.yaml, patterns.yaml, grammar.py),
- ``trainer/`` - the trainer's pack (texts.yaml, words.yaml, grammar.py),
- ``router.example.yaml`` - the example configuration with translated topics (``--home``: the
  examples use the names of the home Home Assistant runs in that language),
- ``model_test.yaml`` - the router and control cases of the active test, translated (answer
  cases are left out: their must / never patterns need a speaker),
- ``REVIEW.md`` - what did not pass the checks, what is always to be read by a speaker (grammar,
  prompts), and where to copy the files.

Every unit is checked as it comes back: a text keeps its ``{fields}``, a word list keeps its type and
the Home Assistant names, a pattern finds its translated examples. What fails keeps the Polish
value and a ``REVIEW`` mark. Reference material for the teacher: the language's built-in Home
Assistant sentences and lists (home-assistant-intents), and with ``--home`` the home's names.
With the writer ``manual`` the tasks are written to ``tasks.jsonl`` and the answers imported with
``--answers`` (the same format as router-trainer handoff).
"""

from __future__ import annotations

import ast
import contextlib
import json
from pathlib import Path
import re
import string
import sys
from typing import Any

import yaml

from . import languages, teacher as teacher_module
from .config import Workspace, load_settings
from .pack_yaml import dump_entry, dump_value

NAMES = {
    "cs": "Czech", "sk": "Slovak", "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "nl": "Dutch", "uk": "Ukrainian", "ru": "Russian", "pt": "Portuguese",
    "sv": "Swedish", "da": "Danish", "nb": "Norwegian", "fi": "Finnish", "hu": "Hungarian",
    "ro": "Romanian", "hr": "Croatian", "sl": "Slovenian", "lt": "Lithuanian", "lv": "Latvian",
}  # fmt: skip
BATCH = 12  # texts per translation task
FIXED_KEYS = (
    "INTENTS", "DOMAINS", "CONTROL_KEYS", "DOMAIN_HINTS", "DONE", "BINARY_STATES", "STATES",
    "PREVIEW_HEADERS", "COMMAND_VARIABLE_ALIASES", "OPEN_CLOSE_VERBS", "FIELD_NAMES",
)  # fmt: skip
SCHEMA_TEXTS = {"type": "object", "properties": {"translations": {"type": "object"}}}
SCHEMA_VALUE = {"type": "object", "properties": {"yaml": {"type": "string"}}}
SCHEMA_PATTERN = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "matches": {"type": "array", "items": {"type": "string"}},
        "not_matches": {"type": "array", "items": {"type": "string"}},
    },
}


def language_name(code: str) -> str:
    return NAMES.get(code, code)


class Pending(RuntimeError):
    """Tasks wait for a manual writer (tasks.jsonl)."""


# --- the translator: a teacher, or the answers of a manual writer --------------------------------


class Translator:
    def __init__(self, ws: Workspace, code: str, out: Path, answers: Path | None = None) -> None:
        self.code = code
        self.name = language_name(code)
        self.out = out
        settings = load_settings(ws)
        self.manual = teacher_module.is_manual(settings, "writer")
        self.teacher = None if self.manual else teacher_module.make(settings, ws.root, "writer")
        self.answers: dict[str, Any] = {}
        if answers:
            from .handoff import parse_answers

            for item in parse_answers(answers.read_text(encoding="utf-8")):
                self.answers[str(item["id"])] = item
        self.pending: list[dict[str, Any]] = []
        self.reference = ""

    def system(self) -> str:
        return (
            f"You translate a smart home voice assistant from Polish to {self.name}. Write what a "
            f"native {self.name} speaker says to a voice assistant at home, naturally, with correct "
            "grammar. Keep every {field} in braces exactly as it is, keep names in English "
            "(HassTurnOn, light, today) and answer with JSON only." + self.reference
        )

    def ask(self, task_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if task_id in self.answers:
            return self.answers[task_id]
        messages = [
            {"role": "system", "content": self.system()},
            {"role": "user", "content": prompt},
        ]
        if self.manual:
            self.pending.append({"id": task_id, "messages": messages, "schema": schema})
            return None
        return self.teacher.json(messages, schema, temperature=0.2, num_predict=4000)


def reference_material(code: str, home: dict[str, Any] | None = None, limit: int = 40) -> str:
    """Built-in Home Assistant sentences, lists and replies of the language (and the home's names)."""
    parts = []
    with contextlib.suppress(Exception):  # no data for the language: no reference
        import home_assistant_intents

        data = home_assistant_intents.get_intents(code)
        sentences = []
        for name in (
            "HassTurnOn",
            "HassTurnOff",
            "HassLightSet",
            "HassGetWeather",
            "HassSetVolume",
        ):
            for block in (data["intents"].get(name) or {}).get("data", [])[:2]:
                sentences += [str(s) for s in block.get("sentences", [])[:3]]
        colors = [v.get("in") for v in (data["lists"].get("color") or {}).get("values", [])][:12]
        replies = list((data.get("responses") or {}).get("errors", {}).values())[:4]
        parts.append(
            "\n\nReference - Home Assistant's own sentences in this language (hassil templates): "
            + "; ".join(sentences[:limit])
            + "\nColour words: "
            + ", ".join(str(c) for c in colors)
            + "\nHome Assistant replies: "
            + " | ".join(str(r) for r in replies)
        )
    if home:
        areas = sorted(set((home.get("areas") or {}).values()))[:20]
        devices = [t.get("name") for t in (home.get("targets") or [])[:30]]
        parts.append(
            f"\nThe home's rooms: {', '.join(areas)}. Devices: {', '.join(map(str, devices))}."
        )
    return "".join(parts)


# --- units of a pack -----------------------------------------------------------------------------


def fields(text: str) -> set[str]:
    try:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}
    except ValueError:
        return {"<broken>"}


def translate_texts(tr: Translator, prefix: str, data: dict[str, Any], review: list[str]) -> dict:
    out = dict(data)
    names = [n for n, v in data.items() if isinstance(v, str) and n != "CODE" and v.strip()]
    for first in range(0, len(names), BATCH):
        part = {name: data[name] for name in names[first : first + BATCH]}
        prompt = (
            "Translate the values of this JSON object. Keys stay. Names ending in _KEY are JSON "
            "key words a model fills in: translate them to one lowercase word without spaces or "
            "accents. Keep leading spaces, line breaks and {fields}.\n"
            + json.dumps(part, ensure_ascii=False)
        )
        reply = tr.ask(f"{prefix}:texts:{first}", prompt, SCHEMA_TEXTS)
        got = (reply or {}).get("translations") or {}
        for name, original in part.items():
            value = got.get(name)
            if not isinstance(value, str) or not value.strip():
                review.append(f"{prefix}/texts.yaml {name}: not translated")
            elif fields(value) != fields(original):
                review.append(f"{prefix}/texts.yaml {name}: the {{fields}} changed - kept Polish")
            else:
                out[name] = value
    out["CODE"] = tr.code
    if "WIKIPEDIA_LANGUAGE" in out:
        out["WIKIPEDIA_LANGUAGE"] = tr.code
    return out


def _same_shape(original: Any, value: Any) -> bool:
    if type(original) is not type(value):
        return False
    if isinstance(original, dict):
        return all(_same_shape(original[k], value[k]) for k in original if k in value)
    return True


def translate_words(tr: Translator, prefix: str, data: dict[str, Any], comments: dict[str, str],
                    review: list[str]) -> dict:  # fmt: skip
    from .languages import PackLoader

    out = dict(data)
    for name, original in data.items():
        if isinstance(original, (int, float)) and not isinstance(original, bool):
            continue  # numbers (STEM_LETTERS) stay - a speaker may tune them
        prompt = (
            f"Translate this YAML value ({name}). What it is: {comments.get(name) or 'see the name'}\n"
            "Translate the words; keep YAML tags (!tuple, !set, !frozenset, !translate), keys that "
            "are Home Assistant or code names (intents, domains, states, colours in English, day "
            "codes) and numbers. Word stems may stay stems of the new language. Return "
            '{"yaml": "<the value as YAML>"}.\n' + dump_value(original)
        )
        reply = tr.ask(f"{prefix}:words:{name}", prompt, SCHEMA_VALUE)
        text = (reply or {}).get("yaml")
        try:
            value = yaml.load(text, Loader=PackLoader) if isinstance(text, str) else None
        except yaml.YAMLError:
            value = None
        if value is None or not _same_shape(original, value):
            review.append(f"{prefix}/words.yaml {name}: no usable translation - kept Polish")
            continue
        if name in FIXED_KEYS and isinstance(original, dict) and set(value) != set(original):
            review.append(f"{prefix}/words.yaml {name}: keys changed - kept Polish")
            continue
        out[name] = value
    return out


def _pattern_ok(spec: dict[str, Any]) -> bool:
    try:
        flags = re.IGNORECASE if "IGNORECASE" in (spec.get("flags") or ()) else 0
        pattern = re.compile(spec["pattern"], flags)
    except (re.error, KeyError, TypeError):
        return False
    return (
        bool(spec.get("matches"))
        and all(pattern.search(t) for t in spec["matches"])
        and not any(pattern.search(t) for t in spec.get("not_matches") or ())
    )


def translate_patterns(tr: Translator, prefix: str, data: dict[str, Any], comments: dict[str, str],
                       review: list[str]) -> dict:  # fmt: skip
    out = {}
    for name, spec in data.items():
        items = spec.get("items") if isinstance(spec, dict) else None
        units = (
            [(f"{name}[{i}]", item) for i, item in enumerate(items)] if items else [(name, spec)]
        )
        translated = []
        for label, item in units:
            prompt = (
                f"A Python regular expression of the assistant ({label}): "
                f"{comments.get(name) or 'see the examples'}\n"
                f"Polish pattern: {item['pattern']}\nIt finds: {item.get('matches') or []}\n"
                f"It must not find: {item.get('not_matches') or []}\n"
                f"Translate the examples to {tr.name} and write the pattern for them (word stems "
                "cover inflected forms; keep the structure: anchors, groups, \\b). Return "
                '{"pattern": ..., "matches": [...], "not_matches": [...]}.'
            )
            reply = tr.ask(f"{prefix}:patterns:{label}", prompt, SCHEMA_PATTERN) or {}
            candidate = {
                **item,
                **{k: reply[k] for k in SCHEMA_PATTERN["properties"] if k in reply},
            }
            if reply and _pattern_ok(candidate):
                translated.append(candidate)
            else:
                review.append(f"{prefix}/patterns.yaml {label}: the pattern does not find its "
                              "examples - kept Polish, write it by hand")  # fmt: skip
                translated.append(item)
        out[name] = {**spec, "items": translated} if items else translated[0]
    return out


def string_literals(source: str) -> list[str]:
    """Text a person reads in grammar.py: string constants with a space or a non-ASCII letter (not
    docstrings, not names like ``HassTurnOn``)."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            text = node.value
            if re.search(r"[^\x00-\x7f]", text) or (
                " " in text and re.search(r"[A-Za-z]{3}", text)
            ):
                found.append(text)
    return list(dict.fromkeys(found))


def translate_grammar(tr: Translator, prefix: str, source: str, review: list[str]) -> str:
    texts = [t for t in string_literals(source) if t.strip()]
    mapping: dict[str, str] = {}
    for first in range(0, len(texts), BATCH):
        part = texts[first : first + BATCH]
        prompt = (
            "Translate these fragments of Python code's text (sentences the assistant says or "
            "sends to a model). Keep leading/trailing spaces and {expressions}. Return "
            '{"translations": {"<Polish>": "<translation>", ...}}.\n'
            + json.dumps(part, ensure_ascii=False)
        )
        reply = tr.ask(f"{prefix}:grammar:{first}", prompt, SCHEMA_TEXTS)
        for original, value in ((reply or {}).get("translations") or {}).items():
            if original in part and isinstance(value, str) and value.strip():
                mapping[original] = value
    out = source
    for original, value in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        for quote in ('"', "'"):
            literal = quote + original.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote
            replacement = quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote
            out = out.replace(literal, replacement)
    header = (
        f"# REVIEW ({tr.name}): the text inside the functions was machine-translated; the grammar "
        "(cases, plural forms, gender, word order) is still Polish logic - adapt it.\n"
    )
    review.append(f"{prefix}/grammar.py: always read by a speaker - {len(mapping)} texts translated, "
                  "the grammar itself is Polish")  # fmt: skip
    try:
        ast.parse(out)
    except SyntaxError as err:
        review.append(f"{prefix}/grammar.py: the translation broke the code ({err}) - kept Polish")
        return header + source
    return header + out


def _comments(path: Path) -> dict[str, str]:
    """The comment above each top-level name of a YAML file (what it is for)."""
    out, block = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            block.append(line.lstrip("# ").strip())
        elif re.match(r"^[A-Z_]+:", line):
            out[line.split(":")[0]] = " ".join(block)
            block = []
        elif not line.strip():
            block = [] if not block or not block[-1] else block
    return out


def _header(path: Path, name: str) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#") and line.strip():
            break
        lines.append(
            line.replace("(Polish)", f"({name}) - machine-translated draft, see REVIEW.md")
        )
    return "\n".join(lines).rstrip() + "\n\n"


def write_yaml(path: Path, header: str, data: dict[str, Any], comments: dict[str, str]) -> None:
    body = "\n".join(dump_entry(name, value, comments.get(name)) for name, value in data.items())
    path.write_text(header + body, encoding="utf-8")


def translate_pack(
    tr: Translator, source: Path, target: Path, prefix: str, review: list[str]
) -> None:
    from .languages import read_yaml

    target.mkdir(parents=True, exist_ok=True)
    for name in ("texts.yaml", "words.yaml", "patterns.yaml"):
        path = source / name
        if not path.is_file():
            continue
        data, comments = read_yaml(path), _comments(path)
        if name == "texts.yaml":
            data = translate_texts(tr, prefix, data, review)
        elif name == "words.yaml":
            data = translate_words(tr, prefix, data, comments, review)
        else:
            data = translate_patterns(tr, prefix, data, comments, review)
        write_yaml(target / name, _header(path, tr.name), data, comments)
    grammar = source / "grammar.py"
    if grammar.is_file():
        source_text = grammar.read_text(encoding="utf-8")
        (target / "grammar.py").write_text(
            translate_grammar(tr, prefix, source_text, review), "utf-8"
        )


# --- router.yaml and the test ---------------------------------------------------------------------


def translate_router_example(tr: Translator, example: Path, review: list[str]) -> dict[str, Any]:
    data = yaml.safe_load(example.read_text(encoding="utf-8"))
    topics = data.get("topics") or {}
    for name, topic in topics.items():
        part = {"description": topic.get("description", ""), "examples": topic.get("examples", [])}
        prompt = (
            f"Translate this topic of the assistant's router ({name}) - description and example "
            f'questions; with the home\'s names where they fit. Return {{"yaml": ...}} with the '
            "same keys.\n" + yaml.safe_dump(part, allow_unicode=True)
        )
        reply = tr.ask(f"router.yaml:{name}", prompt, SCHEMA_VALUE) or {}
        try:
            value = yaml.safe_load(reply.get("yaml") or "")
        except yaml.YAMLError:
            value = None
        if isinstance(value, dict) and isinstance(value.get("examples"), list):
            topic.update({k: value[k] for k in ("description", "examples") if k in value})
        else:
            review.append(f"router.example.yaml topic {name}: not translated")
    data["language"] = tr.code
    data["wikipedia_language"] = tr.code
    return data


def translate_test(tr: Translator, test: dict[str, Any], review: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    router_cases = list(test.get("router") or [])
    texts = [case[0] if isinstance(case, list) else case.get("text") for case in router_cases]
    control = test.get("control") or {}
    commands = [case.get("text") for case in control.get("cases") or []]
    mapping: dict[str, str] = {}
    pool = [t for t in [*texts, *commands] if t]
    for first in range(0, len(pool), BATCH * 2):
        part = pool[first : first + BATCH * 2]
        prompt = (
            "Translate these questions and commands to a voice assistant, keeping their meaning "
            "and their speech-recognition errors (typos stay typos). Return "
            '{"translations": {"<Polish>": "<translation>"}}.\n'
            + json.dumps(part, ensure_ascii=False)
        )
        reply = tr.ask(f"test:{first}", prompt, SCHEMA_TEXTS) or {}
        mapping.update({k: v for k, v in (reply.get("translations") or {}).items() if k in part})
    out["router"] = []
    for case, text in zip(router_cases, texts, strict=True):
        translated = mapping.get(text)
        if not translated:
            review.append(f"model_test.yaml router „{text}”: not translated - left out")
            continue
        out["router"].append(
            [translated, *case[1:]] if isinstance(case, list) else {**case, "text": translated}
        )
    if commands:
        cases = []
        for case in control.get("cases") or []:
            if mapping.get(case.get("text")):
                cases.append({**case, "text": mapping[case["text"]]})
        out["control"] = {**control, "cases": cases}
    review.append("model_test.yaml: answer cases are left out - their must / never patterns need a "
                  "speaker (or generate a new test: router-trainer testgen)")  # fmt: skip
    return out


# --- the command -----------------------------------------------------------------------------------

REVIEW_MD = """# {name} ({code}): a draft to review

Machine-translated from Polish by the writer teacher, then checked. Everything below needs a
{name} speaker's eye - the first group did not pass the checks and kept the Polish value.

## Did not pass the checks

{failed}

## Always read by a speaker

{always}

## Where the files go

1. Assist Router: copy `router/` to `custom_components/assist_router/languages/{code}/` and run
   `.venv/bin/python tools/check_language.py custom_components/assist_router/languages/{code}`,
   then `make test`. Send a pull request with the folder.
2. The trainer: copy `trainer/` to `router_trainer/languages/{code}/` and run
   `router-trainer languages --check {code}`, then `make test`.
3. Home Assistant: `router.example.yaml` is a start for `/config/assist/router.yaml`
   (`language: {code}`); `model_test.yaml` for `/config/assist/model_test.yaml`.
4. `router-trainer language check {code}` runs both checks on this folder before copying.
"""


def new(ws: Workspace, code: str, router_repo: Path, home: bool = False,
        answers: Path | None = None) -> dict[str, Any]:  # fmt: skip
    if not re.fullmatch(r"[a-z]{2,3}", code):
        raise ValueError("the language code: two or three lower-case letters (cs, en, de)")
    if code == languages.REFERENCE:
        raise ValueError("pl is the reference language")
    router_pack = router_repo / "custom_components" / "assist_router" / "languages" / "pl"
    if not router_pack.is_dir():
        raise FileNotFoundError(f"{router_pack} missing - the Assist Router repository with packs")
    out = ws.root / "languages" / code
    out.mkdir(parents=True, exist_ok=True)
    tr = Translator(ws, code, out, answers)
    home_data = None
    if home:
        from . import context

        home_data = context.make(ws).home_data()
    tr.reference = reference_material(code, home_data)
    review: list[str] = []
    translate_pack(tr, router_pack, out / "router", "router", review)
    translate_pack(tr, languages.FOLDER / languages.REFERENCE, out / "trainer", "trainer", review)
    example = router_repo / "router.example.yaml"
    if example.is_file():
        data = translate_router_example(tr, example, review)
        (out / "router.example.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100), "utf-8"
        )
    settings = load_settings(ws)
    test_file = ws.path(settings["inputs"]["tests"])
    if test_file.is_file():
        test = yaml.safe_load(test_file.read_text(encoding="utf-8")) or {}
        (out / "model_test.yaml").write_text(
            yaml.safe_dump(translate_test(tr, test, review), allow_unicode=True, sort_keys=False),
            "utf-8",
        )
    if tr.pending:
        with (out / "tasks.jsonl").open("w", encoding="utf-8") as handle:
            for task in tr.pending:
                handle.write(json.dumps(task, ensure_ascii=False) + "\n")
    always = [r for r in review if "always" in r or "answer cases" in r]
    failed = [r for r in review if r not in always]
    (out / "REVIEW.md").write_text(
        REVIEW_MD.format(
            name=tr.name,
            code=code,
            failed="\n".join(f"- {r}" for r in failed) or "- nothing",
            always="\n".join(f"- {r}" for r in always) or "- nothing",
        ),
        "utf-8",
    )
    return {"code": code, "folder": str(out), "review": len(failed), "pending": len(tr.pending)}


def check(ws: Workspace, code: str, router_repo: Path) -> dict[str, list[str]]:
    """Both checks on the draft (or on the installed packs when there is no draft)."""
    out = ws.root / "languages" / code
    sys.path.insert(0, str(router_repo))
    from custom_components.assist_router.languages import check as router_check

    router_folder = out / "router"
    if not router_folder.is_dir():
        router_folder = router_repo / "custom_components" / "assist_router" / "languages" / code
    trainer_folder = out / "trainer"
    if not trainer_folder.is_dir():
        trainer_folder = languages.FOLDER / code
    return {
        "router": router_check.problems(router_folder),
        "trainer": languages.problems(trainer_folder),
    }
