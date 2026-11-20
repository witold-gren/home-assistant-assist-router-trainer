"""Generate a test from the home and the question log (``router-trainer testgen``).

Two models, in two phases (they do not fit the graphics card together):

1. the **test writer** (``ollama.test_writer``, another model than the teacher of the training
   data, so the test does not favour the teacher's style) labels the real log questions and
   writes the missing questions, commands and Wikipedia questions;
2. the **judge** (the teacher) checks: a router case stays when both models give the same topic,
   a command when the judge's parse matches the plan, an answer case when the judge finds facts
   that are literally in the data or the article.

Expectations come from Python where possible (the command plan, made-up data with computed
facts). Sentences that are router.yaml examples or are like the training data already generated
are left out. The result - test file, snapshot, card - has the format of the router repository's
benchmark, so ``model_benchmark.py`` and the evaluation use it unchanged.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import random
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .. import teacher as teacher_module
from ..context import Context
from ..generate import answers as answers_gen, control as control_gen, router as router_gen
from ..generate.common import list_schema, progress, read_jsonl, sentences_of, stage
from ..holdout import Holdout, normalize
from ..teacher import Teacher, start_local
from . import facts, store

BATCH = 15


def _avoid(ctx: Context) -> tuple[set[str], Holdout]:
    """router.yaml examples (they are in the prompt) and the training data generated so far."""
    examples = {normalize(e) for t in ctx.config.topics.values() for e in t.examples}
    texts = [
        row["text"]
        for role in ("router", "control", "answers")
        for row in read_jsonl(ctx.ws.generated / f"{role}.jsonl")
    ]
    return examples, Holdout(texts)


def _ok(text: str, examples: set[str], training: Holdout, seen: set[str]) -> bool:
    key = normalize(text)
    if not key or key in examples or key in seen or training.match(text):
        return False
    seen.add(key)
    return True


def _topic(model: Teacher, ctx: Context, text: str) -> str | None:
    schema = ctx.integ.router_schema(ctx.config)
    reply = model.json(ctx.integ.router_messages(ctx.config, text), schema, num_predict=30)
    topic = (reply or {}).get(ctx.integ.lang.TOPIC_KEY)
    return topic if topic in ctx.config.topics else None


def _write_questions(
    ctx: Context, writer: Teacher, topic: Any, count: int, hint: str, rng: random.Random
) -> list[str]:
    key = ctx.pack.SENTENCES_KEY
    out: list[str] = []
    for _ in range(max(1, -(-count // BATCH))):
        prompt = ctx.pack.paraphrase_prompt(
            ctx.config.household,
            topic.name,
            topic.description,
            list(topic.examples),
            BATCH,
            ctx.pack.TEST_STYLE,
            hint,
        )
        reply = writer.json(
            [{"role": "user", "content": prompt}],
            list_schema(key),
            temperature=0.9,
            num_predict=1500,
            seed=rng.randrange(1 << 30),
        )
        out += sentences_of(reply, key)
    return out


def _judge_facts(judge: Teacher, ctx: Context, question: str, source: str, what: str) -> tuple:
    schema = {
        "type": "object",
        "properties": {
            ctx.pack.FACTS_KEY: {"type": "array", "items": {"type": "string"}},
        },
        "required": [ctx.pack.FACTS_KEY],
    }
    prompt = ctx.pack.facts_prompt(question, source, what)
    reply = judge.json([{"role": "user", "content": prompt}], schema, num_predict=300) or {}
    must = facts.to_patterns(
        reply.get(ctx.pack.FACTS_KEY) or [], source, question=question,
        generic=frozenset(ctx.pack.FACT_GENERIC), stem=ctx.pack.STEM_LETTERS,
        swaps=ctx.pack.INFLECTION_SWAPS,
    )  # fmt: skip
    must = facts.required(must)
    # no "never" from the judge: a good answer may name other days or people for context
    never: list[str] = []
    return must, never


def _expect(label: control_gen.Label) -> dict[str, Any]:
    """The test's expectation of a planned command (keys of the benchmark's results)."""
    out = {k: v for k, v in label.fields.items() if k != "name" and v not in (None, False)}
    if label.device:
        out["device"] = label.device
    return out


def build(ctx: Context, name: str) -> Path:
    stage(f"test {name}")
    cfg = ctx.settings["test"]
    rng = random.Random(f"{cfg['seed']}:{name}")
    dropped: Counter[str] = Counter()
    examples, training = _avoid(ctx)
    seen: set[str] = set()
    url = start_local(ctx.settings, ctx.ws.root)
    ha_url = ctx.settings["home_assistant"]["url"].rstrip("/")
    home_data = ctx.integ.snapshot_data.home(ha_url, ctx.token())
    topics = list(ctx.config.topics.values())
    data_topics = answers_gen.data_topics(ctx)

    # --- phase 1: the test writer ------------------------------------------------------------
    stage("test writer")
    # one model on the card at a time: the teacher (judge) leaves it for the writer
    Teacher(url, ctx.settings["ollama"]["teacher"]).unload()
    writer = teacher_module.make(ctx.settings, ctx.ws.root, "test_writer")
    log = [q for q in router_gen.log_texts(ctx.input("log")) if _ok(q, examples, training, seen)]
    writer_topics = {}
    for i, question in enumerate(log):
        writer_topics[question] = _topic(writer, ctx, question)
        progress("test", "log labels", i + 1, len(log))
    written: dict[str, list[str]] = {}
    for i, topic in enumerate(topics):
        hint = router_gen.topic_hint(ctx, topic, home_data, rng)
        texts = _write_questions(ctx, writer, topic, cfg["router_per_topic"] * 2, hint, rng)
        written[topic.name] = [t for t in texts if _ok(t, examples, training, seen)]
        progress("test", "router questions", i + 1, len(topics))
    plans = []
    planned = int(cfg["control"] * cfg.get("control_overhead", 4))  # about half is dropped
    for i in range(planned):
        label = None
        while label is None:
            label = control_gen.plan(ctx, home_data, rng)
        style = ctx.pack.COMMAND_STYLES[i % len(ctx.pack.COMMAND_STYLES)]
        prompt = ctx.pack.command_prompt(control_gen.details(ctx, label), 1, style)
        reply = writer.json(
            [{"role": "user", "content": prompt}],
            list_schema(ctx.pack.SENTENCES_KEY),
            temperature=0.9,
            num_predict=200,
        )
        for text in sentences_of(reply, ctx.pack.SENTENCES_KEY)[:1]:
            if _ok(text, examples, training, seen):
                plans.append((label, text))
        progress("test", "commands", i + 1, planned)
    real_questions = {}
    for topic in data_topics:
        texts = _write_questions(ctx, writer, topic, cfg["real_per_topic"] * 2, "", rng)
        real_questions[topic.name] = [t for t in texts if _ok(t, examples, training, seen)]
    # titles of the training pool (router knowledge questions, summaries) are not used
    training_pool = ctx.ws.generated / "wiki_titles.json"
    used_titles = {normalize(t) for t in router_gen.wikipedia_titles(training_pool, 0, set())}
    pool = router_gen.wikipedia_titles(
        ctx.ws.generated / "wiki_titles_test.json",
        cfg["wikipedia"] * 4,
        used_titles,
        ctx.config.wikipedia_language,
    )
    rng.shuffle(pool)
    wiki_questions = []
    for start in range(0, min(len(pool), cfg["wikipedia"] * 3), 10):
        batch = pool[start : start + 10]
        reply = writer.json(
            [{"role": "user", "content": ctx.pack.wiki_question_prompt(batch)}],
            list_schema(ctx.pack.QUESTIONS_KEY),
            temperature=0.5,
            num_predict=800,
        )
        for title, question in zip(
            batch, sentences_of(reply, ctx.pack.QUESTIONS_KEY), strict=False
        ):
            if _ok(question, examples, training, seen):
                wiki_questions.append((title, question))
    if hasattr(writer, "unload") and not isinstance(writer, teacher_module.CachedTeacher):
        writer.unload()  # the local Ollama frees the card for the judge

    # --- phase 2: the judge ------------------------------------------------------------------
    stage("test judge")
    judge = ctx.teacher("judge")
    router_cases: list[list[str]] = []
    for i, topic in enumerate(topics):
        picked = []
        for question in log:
            if len(picked) >= cfg["router_per_topic"]:
                break
            if writer_topics.get(question) == topic.name:
                if _topic(judge, ctx, question) == topic.name:
                    picked.append(question)
                else:
                    dropped["router: models disagree"] += 1
        for question in written.get(topic.name, []):
            if len(picked) >= cfg["router_per_topic"]:
                break
            if _topic(judge, ctx, question) == topic.name:
                picked.append(question)
            else:
                dropped["router: judge picked another topic"] += 1
        router_cases += [[q, topic.name] for q in picked]
        progress("test", "router", i + 1, len(topics))

    control_cases = []
    schema = ctx.integ.control_schema(home_data)
    for label, text in plans:
        if len(control_cases) >= cfg["control"]:
            break
        messages = ctx.integ.control_messages(home_data, ctx.config.household, text)
        command = ctx.integ.parse_command(
            home_data, json.dumps(judge.json(messages, schema, num_predict=160))
        )
        match = (
            ctx.integ.find_target(home_data, command, messages[1]["content"]) if command else None
        )
        device = match.target.name if match and match.target else None
        if control_gen.matches(label, command, device):
            control_cases.append({"text": text, "expect": _expect(label)})
        else:
            dropped["control: parse unlike the plan"] += 1
        progress("test", "control", len(control_cases), cfg["control"])

    tz = ZoneInfo(ctx.settings["home_assistant"]["time_zone"])
    now = datetime.now(tz).replace(second=0, microsecond=0)
    names = [p.name for p in ctx.config.people.values()]
    given = []
    for i in range(cfg["answers"]):
        scenario = ctx.pack.given_scenario(rng, now, names)
        given.append(
            {
                "name": f"given_{i + 1}",
                "data": scenario["data"],
                "question": scenario["question"],
                "must": scenario["must"],
                "never": scenario["never"],
            }
        )

    topic_data = ctx.integ.topic_data
    home_now = topic_data.load_home(topic_data.HA(ha_url, ctx.token()))
    speakers = [p.speaker for p in ctx.config.people.values() if p.speaker]
    real_cases, live = [], {}
    for topic in data_topics:
        kept = 0
        for question in real_questions.get(topic.name, []):
            if kept >= cfg["real_per_topic"] or len(real_cases) >= cfg["real_max"]:
                break
            speaker = rng.choice(speakers) if speakers and rng.random() < 0.7 else None
            try:
                entry = topic_data.topic_data(
                    home_now, ctx.config, topic.name, question, speaker, now
                )
            except Exception as err:  # a failed HA call skips the question
                print(f"!! {topic.name}: {err}", flush=True)
                continue
            if not entry["data"].strip():
                dropped["real: no data"] += 1
                continue
            # a question of this topic (the writer sometimes writes a command instead)
            if _topic(judge, ctx, question) != topic.name:
                dropped["real: judge picked another topic"] += 1
                continue
            must, never = _judge_facts(judge, ctx, question, entry["data"], "danych")
            if not must:
                dropped["real: no fact in the data"] += 1
                continue
            case_name = f"real_{topic.name}_{kept + 1}"
            case = {
                "name": case_name,
                "topic": topic.name,
                "question": question,
                "speaker": speaker,
                "must": must,
                "never": never,
            }
            if topic.answer_tokens > answers_gen.ANSWER_TOKENS:
                case["max_sentences"] = 6
            real_cases.append(case)
            live[case_name] = {"topic": topic.name, "question": question, **entry}
            kept += 1
        progress("test", "real", len(real_cases), cfg["real_max"])

    wiki, wiki_cases, wiki_snapshot = {}, [], {}
    for _title, question in wiki_questions:
        if len(wiki_cases) >= cfg["wikipedia"]:
            break
        try:
            found, article = ctx.integ.snapshot_data.wikipedia(
                question, ctx.config.wikipedia_language
            )
        except (OSError, KeyError, StopIteration):
            continue
        if normalize(found) in used_titles or len(article) < 300:
            dropped["wikipedia: article missing or used in training"] += 1
            continue
        must, never = _judge_facts(judge, ctx, question, article, ctx.pack.ARTICLE_WORD)
        if not must:
            dropped["wikipedia: no fact in the article"] += 1
            continue
        key = f"wiki_{len(wiki_cases) + 1}"
        wiki[key] = question
        wiki_snapshot[key] = {"phrase": question, "title": found, "text": article}
        wiki_cases.append(
            {"name": key, "source": key, "question": question, "must": must, "never": never}
        )
        progress("test", "wikipedia", len(wiki_cases), cfg["wikipedia"])

    system = (ctx.config.answer_prompt or ctx.integ.lang.ANSWER_PROMPT).format(
        household=ctx.config.household,
        now=ctx.integ.router.polish_now(now),
        sentences=ctx.config.sentences,
    )
    tests = {
        "router": router_cases,
        "answers": {"system": system, "max_sentences": 3, "cases": given},
        "real": {"max_sentences": 3, "cases": real_cases},
        "wiki_answers": {
            "prompt": "summary",
            "min_sentences": 2,
            "max_sentences": 5,
            "cases": wiki_cases,
        },
        "wiki": wiki,
        "control": {"num_ctx": 8192, "household": ctx.config.household, "cases": control_cases},
    }
    snapshot = {
        "taken": now.strftime("%Y-%m-%d %H:%M"),
        "sources": {},
        "wiki": wiki_snapshot,
        "now": now.isoformat(),
        "live": live,
        "home": home_data,
    }
    return save(ctx, name, tests, snapshot, dropped)


HEADER = """# Generated test ({name}, {created}) - router-trainer testgen; nobody wrote it by hand.
# Writer: {writer} (another model than the teacher of the training data); judge: {judge}.
# router: real log questions and the writer's questions, kept when both models give the topic.
# control: commands planned from the home, written by the writer; expect = the plan.
# answers: made-up data with facts computed in Python; real / wiki_answers: facts the judge
#   found word for word in the data (model_test_data.yaml) or the article.
"""


def save(ctx: Context, name: str, tests: dict, snapshot: dict, dropped: Counter) -> Path:
    folder = store.test_dir(ctx.ws, name)
    folder.mkdir(parents=True, exist_ok=True)
    header = HEADER.format(
        name=name,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        writer=ctx.settings["ollama"]["test_writer"],
        judge=ctx.settings["ollama"]["teacher"],
    )
    body = yaml.safe_dump(tests, allow_unicode=True, sort_keys=False, width=100)
    (folder / store.TEST_FILE).write_text(header + "\n" + body, encoding="utf-8")
    (folder / store.DATA_FILE).write_text(
        yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
    counts = {s: len(store.section_cases(tests, s)) for s in store.SECTIONS}
    card = {
        "name": name,
        "created": datetime.now().isoformat(timespec="minutes"),
        "counts": counts,
        "dropped": dict(dropped),
        "writer": ctx.settings["ollama"]["test_writer"],
        "judge": ctx.settings["ollama"]["teacher"],
    }
    (folder / store.CARD_FILE).write_text(
        json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    store.set_active(ctx.ws, name)
    print(f"test {name}: {counts}, dropped {dict(dropped)} - now the active test", flush=True)
    return folder
