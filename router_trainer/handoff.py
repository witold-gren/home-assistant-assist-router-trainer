"""The teacher by hand: tasks for any AI chat (or a person) out, the answers back in.

Writing and judging are separate (``teacher.writer`` / ``teacher.judge`` = ``manual``):

- **writer**: the tasks the trainer would give its teacher - paraphrases of each topic, sentences
  on both sides of the borders that get mixed up, commands for each planned control command. The
  imported sentences become training rows (source ``external``) and go through the same checks as
  the teacher's: the frozen test, the label check (by the judge - a model or by hand), the parse
  of the commands back by the judge.
- **judge**: the sentences waiting for a topic (generated/handoff/judge-pending.json) - for an AI
  chat as the router's own prompt, for a person as a table (sentence; topic from a list).

``export`` writes a folder: ``requests.jsonl`` (one task per line: id, messages, the answer
schema), ``prompts.md`` (the same to paste into a chat, in parts) and ``README.md``; the judge
also gets ``table.csv``. ``import_answers`` reads JSON objects with an ``id`` (one per line, a
list, or anywhere in a pasted chat answer) or, for the judge, the filled table. Each import is
idempotent: an answered task is not asked again.
"""

from __future__ import annotations

import csv
from datetime import datetime
import io
import json
from pathlib import Path
from typing import Any

from .context import Context
from .generate import control as control_gen, labels as labels_gen, router as router_gen
from .generate.common import JsonlWriter, list_schema, read_jsonl, sentences_of
from .holdout import normalize

ROLES = ("writer", "judge")
PER_PROMPT = 25  # sentences asked for in one paraphrase task (as the teacher)
CHAT_PART = 20  # tasks per part of prompts.md


def folder(ctx: Context) -> Path:
    return ctx.ws.generated / "handoff"


def _tasks_file(ctx: Context) -> Path:
    return folder(ctx) / "tasks.json"


def load_tasks(ctx: Context) -> dict[str, dict[str, Any]]:
    path = _tasks_file(ctx)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save_tasks(ctx: Context, tasks: dict[str, dict[str, Any]]) -> None:
    folder(ctx).mkdir(parents=True, exist_ok=True)
    _tasks_file(ctx).write_text(json.dumps(tasks, ensure_ascii=False, indent=1), "utf-8")


def _answered(ctx: Context) -> set[str]:
    return {row["id"] for row in read_jsonl(folder(ctx) / "answered.jsonl")}


def _mark_answered(ctx: Context, ids: list[str]) -> None:
    folder(ctx).mkdir(parents=True, exist_ok=True)
    with (folder(ctx) / "answered.jsonl").open("a", encoding="utf-8") as handle:
        for task_id in ids:
            handle.write(json.dumps({"id": task_id}) + "\n")


# --- the tasks ----------------------------------------------------------------------------------


def writer_tasks(ctx: Context, per_topic: int | None = None) -> list[dict[str, Any]]:
    """Paraphrases per topic, contrast pairs and control commands - the teacher's prompts."""
    settings = ctx.settings["generate"]["router"]
    per_topic = per_topic or int(settings["paraphrases_per_topic"])
    home_data = ctx.home_data()
    rng = ctx.rng("handoff")
    pack = ctx.pack
    key = pack.SENTENCES_KEY
    tasks = []
    for topic in ctx.config.topics.values():
        for number in range(-(-per_topic // PER_PROMPT)):
            prompt = pack.paraphrase_prompt(
                ctx.config.household,
                topic.name,
                topic.description,
                list(topic.examples),
                PER_PROMPT,
                pack.STYLES[number % len(pack.STYLES)],
                router_gen.topic_hint(ctx, topic, home_data, rng),
            )
            task_id = f"paraphrase:{topic.name}:{number}"
            tasks.append({"id": task_id, "kind": "paraphrase", "topic": topic.name,
                          "prompt": prompt, "schema": list_schema(key)})  # fmt: skip
    contrast = settings.get("contrast") or {}
    per_side = int(contrast.get("per_side") or 0)
    for first, second in labels_gen.contrast_pairs(ctx) if per_side else []:
        topics = [ctx.config.topics[first], ctx.config.topics[second]]
        for number in range(-(-per_side // labels_gen.CONTRAST_BATCH)):
            prompt = pack.contrast_prompt(
                ctx.config.household,
                [(t.name, t.description, list(t.examples)) for t in topics],
                labels_gen.CONTRAST_BATCH,
                pack.STYLES[number % len(pack.STYLES)],
                router_gen.topic_hint(ctx, topics[number % 2], home_data, rng),
            )
            tasks.append({"id": f"contrast:{first}|{second}:{number}", "kind": "contrast",
                          "topics": [first, second], "prompt": prompt,
                          "schema": labels_gen.contrast_schema(pack.CONTRAST_KEYS)})  # fmt: skip
    count = ctx.settings["generate"]["control"]["sentences_per_label"]
    for index, label, style, _ in control_gen.plans(ctx, home_data):
        prompt = pack.command_prompt(control_gen.details(ctx, label), count, style)
        tasks.append({"id": f"control:{index}", "kind": "control", "label": index,
                      "prompt": prompt, "schema": list_schema(key)})  # fmt: skip
    return tasks


def judge_tasks(ctx: Context) -> list[dict[str, Any]]:
    """The sentences waiting for a topic, with the router's own prompt."""
    checker = labels_gen.Checker(ctx, label=lambda text: None)
    path = checker.pending_path
    waiting = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    schema = ctx.integ.router_schema(ctx.config)
    tasks = []
    for text in dict.fromkeys(waiting):
        if checker.known(text):
            continue
        messages = ctx.integ.router_messages(ctx.config, text)
        tasks.append({"id": f"judge:{normalize(text)[:80]}", "kind": "judge", "text": text,
                      "messages": messages, "schema": schema})  # fmt: skip
    return tasks


# --- export -------------------------------------------------------------------------------------

README = """# {role}: tasks for the Assist Router trainer / zadania dla trenera Assist Routera

{count} tasks. Give each prompt to an AI chat (or answer it yourself) and save every answer as
one JSON object with the task's id - one per line in a file, or pasted together:

    {example}

Then import the file: `router-trainer handoff import {role} FILE` (or Import in the studio). The
answers go through the same checks as the trainer's own teacher. Tasks answered once are not
exported again.

Każde polecenie daj dowolnemu czatowi AI (albo odpowiedz sam) i zapisz każdą odpowiedź jako jeden
obiekt JSON z identyfikatorem zadania - po jednym w linii albo wklejone razem. Potem zaimportuj
plik: `router-trainer handoff import {role} PLIK` (albo Import w studiu).

Files / pliki: requests.jsonl (id, messages, schema), prompts.md (to paste / do wklejenia){table}
"""


def _messages(task: dict[str, Any]) -> list[dict[str, str]]:
    return task.get("messages") or [{"role": "user", "content": task["prompt"]}]


def export(ctx: Context, role: str, out: Path | None = None, per_topic: int | None = None) -> dict:
    if role not in ROLES:
        raise ValueError(f"role: one of {', '.join(ROLES)}")
    tasks = writer_tasks(ctx, per_topic) if role == "writer" else judge_tasks(ctx)
    done = _answered(ctx)
    tasks = [task for task in tasks if task["id"] not in done]
    registry = load_tasks(ctx)
    registry.update({task["id"]: task for task in tasks})
    _save_tasks(ctx, registry)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out or ctx.ws.root / "handoff" / f"{role}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "requests.jsonl").open("w", encoding="utf-8") as handle:
        for task in tasks:
            row = {"id": task["id"], "messages": _messages(task), "schema": task["schema"]}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    parts = []
    for first in range(0, len(tasks), CHAT_PART):
        blocks = []
        for task in tasks[first : first + CHAT_PART]:
            text = "\n\n".join(m["content"] for m in _messages(task))
            blocks.append(f"### {task['id']}\n\n{text}")
        parts.append(f"## Part {first // CHAT_PART + 1}\n\n" + "\n\n".join(blocks))
    (out / "prompts.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    table = ""
    if role == "judge":
        topics = ", ".join(ctx.config.topics)
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["text", "topic"])
        for task in tasks:
            writer.writerow([task["text"], ""])
        (out / "table.csv").write_text(buffer.getvalue(), encoding="utf-8")
        table = f", table.csv (sentence; topic - one of: {topics})"
    key = ctx.integ.lang.TOPIC_KEY if role == "judge" else ctx.pack.SENTENCES_KEY
    example_value = '"..."' if role == "judge" else '["...", "..."]'
    example = f'{{"id": "{tasks[0]["id"] if tasks else "..."}", "{key}": {example_value}}}'
    (out / "README.md").write_text(
        README.format(role=role, count=len(tasks), example=example, table=table), "utf-8"
    )
    return {"role": role, "tasks": len(tasks), "folder": str(out)}


# --- import -------------------------------------------------------------------------------------


def parse_answers(text: str) -> list[dict[str, Any]]:
    """Every JSON object with an ``id`` in the text: lines, a list, or a pasted chat answer."""
    found: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    position = 0
    while True:
        start = min((i for i in (text.find("{", position), text.find("[", position)) if i >= 0),
                    default=-1)  # fmt: skip
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            position = start + 1
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict) and "id" in item:
                found.append(item)
        position = end
    return found


def _table(text: str) -> list[tuple[str, str]]:
    rows = csv.reader(io.StringIO(text), delimiter=";")
    return [(row[0], row[1].strip()) for row in rows if len(row) >= 2 and row[0] != "text"]


def import_answers(ctx: Context, role: str, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if role == "judge":
        return _import_judge(ctx, text)
    if role == "writer":
        return _import_writer(ctx, text)
    raise ValueError(f"role: one of {', '.join(ROLES)}")


def _import_writer(ctx: Context, text: str) -> dict[str, Any]:
    tasks = load_tasks(ctx)
    holdout = ctx.holdout()
    pack = ctx.pack
    counts = {"sentences": 0, "like_test": 0, "unknown_task": 0}
    answered = []
    control_rows = []
    with JsonlWriter(ctx.ws.generated / "router.jsonl") as writer:
        for answer in parse_answers(text):
            task = tasks.get(str(answer["id"]))
            if task is None:
                counts["unknown_task"] += 1
                continue
            answered.append(task["id"])
            if task["kind"] == "contrast":
                sides = zip(pack.CONTRAST_KEYS, task["topics"], strict=True)
                written = [(t, topic) for key, topic in sides for t in sentences_of(answer, key)]
            else:
                written = [(t, task.get("topic")) for t in sentences_of(answer, pack.SENTENCES_KEY)]
            for sentence, topic in written:
                if holdout.match(sentence):
                    counts["like_test"] += 1
                    continue
                counts["sentences"] += 1
                if task["kind"] == "control":
                    control_rows.append({"label": task["label"], "text": sentence})
                    continue
                writer.write({"role": "router", "part": f"external:{topic}", "text": sentence,
                              "topic": topic, "source": "external"})  # fmt: skip
    if control_rows:
        folder(ctx).mkdir(parents=True, exist_ok=True)
        with (folder(ctx) / "control-external.jsonl").open("a", encoding="utf-8") as handle:
            for row in control_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    _mark_answered(ctx, answered)
    return {"role": "writer", "answers": len(answered), **counts}


def _import_judge(ctx: Context, text: str) -> dict[str, Any]:
    checker = labels_gen.Checker(ctx, label=lambda sentence: None)
    tasks = load_tasks(ctx)
    topic_key = ctx.integ.lang.TOPIC_KEY
    pairs: list[tuple[str, str]] = []
    answers = parse_answers(text)
    if answers:
        for answer in answers:
            task = tasks.get(str(answer["id"]))
            if task and task["kind"] == "judge":
                pairs.append((task["text"], str(answer.get(topic_key) or "")))
    else:
        pairs = _table(text)
    counts = {"judged": 0, "unknown_topic": 0}
    for sentence, topic in pairs:
        if topic not in ctx.config.topics:
            counts["unknown_topic"] += 1
            continue
        checker.cache[normalize(sentence)] = topic
        counts["judged"] += 1
    checker.save()
    _mark_answered(ctx, [f"judge:{normalize(s)[:80]}" for s, t in pairs if t in ctx.config.topics])
    return {"role": "judge", **counts}
