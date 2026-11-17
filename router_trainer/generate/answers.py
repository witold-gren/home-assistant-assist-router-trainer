"""Answer examples: the integration's answer prompt with data -> a short spoken answer.

Three parts, every answer written by the teacher and kept only when it passes a check:
- ``given``: made-up data (pocket money, calendars, lessons, car …) with the facts a good
  answer must and must not contain computed in Python; checked with the test's own ``check``;
- ``live``: your current Home Assistant data built exactly as the integration builds it
  (``topic_data``) for questions written for the topic (router paraphrases, never test
  questions); checked for form (length, no markdown, no raw states);
- ``wikipedia``: summaries of random articles (never the test articles) with the integration's
  summary prompt; checked for length and form.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from ..context import Context
from ..holdout import normalize
from .common import JsonlWriter, list_schema, progress, read_jsonl, sentences_of, stage
from .router import wikipedia_titles

ANSWER_TOKENS = 160  # as conversation.py
SUMMARY_TOKENS_PER_SENTENCE = 70
# HA states that must be put into words (not "on"/"off": „on” is a Polish pronoun)
RAW_STATES = re.compile(r"\b(unavailable|unknown|null|true|false)\b")
MARKUP = re.compile(r"(\*\*|^#|\n\s*[-*•]\s|<\||\[\d+\]|https?://)")
WIKI_BATCH = 10


def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def form_problems(answer: str, min_sentences: int, max_sentences: int) -> list[str]:
    """What makes an answer unfit to be read aloud."""
    problems = []
    if not answer.strip():
        return ["empty"]
    if MARKUP.search(answer):
        problems.append("markup")
    if RAW_STATES.search(answer.lower()):
        problems.append("raw state")
    count = sentence_count(answer)
    if count > max_sentences:
        problems.append(f"too long: {count}")
    elif count < min_sentences:
        problems.append(f"too short: {count}")
    return problems


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return row["part"].split(":")[0], row["id"]


def random_now(rng: Any) -> datetime:
    """A moment of an ordinary day of the coming year (data of made-up scenarios)."""
    start = datetime(2026, 1, 5, 7, 0)
    return start + timedelta(days=rng.randrange(0, 360), minutes=rng.randrange(0, 14 * 60))


def given(ctx: Context, writer: JsonlWriter) -> None:
    target = ctx.settings["generate"]["answers"]["given"]
    rng = ctx.rng("given")
    names = [person.name for person in ctx.config.people.values()]
    teacher = ctx.teacher()
    holdout = ctx.holdout()
    rejected = 0
    for index in range(target * 2):  # some answers fail the check
        scenario = ctx.pack.given_scenario(rng, random_now(rng), names)
        row_id = f"given:{index}"
        if writer.count("given") >= target:
            break
        if ("given", row_id) in writer.seen:
            continue
        if holdout.match(scenario["question"]):
            rejected += 1
            continue
        now = datetime.fromisoformat(scenario["now"]) if scenario.get("now") else random_now(rng)
        messages = ctx.integ.answer_messages(
            ctx.config, now, scenario["data"], scenario["question"]
        )
        answer = teacher.text(messages, temperature=0.2, num_predict=ANSWER_TOKENS)
        case = {"must": scenario["must"], "never": scenario["never"]}
        problems = ctx.integ.benchmark.check(answer, case, 1, 3) + form_problems(answer, 1, 3)
        if problems:
            rejected += 1
        else:
            writer.write(
                {
                    "role": "answers",
                    "part": f"given:{scenario['kind']}",
                    "id": row_id,
                    "text": scenario["question"],
                    "messages": messages,
                    "answer": answer,
                    "source": "teacher",
                }
            )
        progress("answers", "given", writer.count("given"), target, rejected)


def data_topics(ctx: Context) -> list[Any]:
    """Topics answered from HA data (not commands, knowledge or gibberish)."""
    return [
        t
        for t in ctx.config.topics.values()
        if (t.entities or t.details or t.fetch) and not (t.control or t.search or t.unclear)
    ]


def topic_questions(ctx: Context, topic: str) -> list[str]:
    """Questions for a topic: the router data written for it (already without test sentences)."""
    rows = read_jsonl(ctx.ws.generated / "router.jsonl")
    sources = {"paraphrase", "log", "example"}
    return list(
        dict.fromkeys(r["text"] for r in rows if r["topic"] == topic and r["source"] in sources)
    )


def live(ctx: Context, writer: JsonlWriter) -> None:
    per_topic = ctx.settings["generate"]["answers"]["live_per_topic"]
    ha_settings = ctx.settings["home_assistant"]
    topic_data = ctx.integ.topic_data
    home_now = topic_data.load_home(topic_data.HA(ha_settings["url"], ctx.token()))
    now = datetime.now(ZoneInfo(ha_settings["time_zone"])).replace(second=0, microsecond=0)
    speakers = [p.speaker for p in ctx.config.people.values() if p.speaker]
    rng = ctx.rng("live")
    teacher = ctx.teacher()
    topics = data_topics(ctx)
    target = per_topic * len(topics)
    rejected = 0
    for topic in topics:
        questions = topic_questions(ctx, topic.name)
        rng.shuffle(questions)
        kept = 0
        for question in questions:
            if kept >= per_topic:
                break
            row_id = f"live:{topic.name}:{normalize(question)}"
            if ("live", row_id) in writer.seen:
                kept += 1
                continue
            speaker = rng.choice(speakers) if speakers and rng.random() < 0.7 else None
            try:
                entry = topic_data.topic_data(
                    home_now, ctx.config, topic.name, question, speaker, now
                )
            except Exception as err:
                print(f"!! {topic.name}: {err}", flush=True)
                continue
            if not entry["data"].strip():
                continue
            messages = ctx.integ.answer_messages(
                ctx.config, now, entry["data"], question, entry["speaker"], entry["hint"]
            )
            tokens = topic.answer_tokens or ANSWER_TOKENS
            answer = teacher.text(messages, temperature=0.2, num_predict=tokens)
            if form_problems(answer, 1, 6 if topic.answer_tokens > ANSWER_TOKENS else 3):
                rejected += 1
                continue
            writer.write(
                {
                    "role": "answers",
                    "part": f"live:{topic.name}",
                    "id": row_id,
                    "text": question,
                    "messages": messages,
                    "answer": answer,
                    "source": "teacher",
                }
            )
            kept += 1
            progress("answers", "live", writer.count("live"), target, rejected)


def wikipedia(ctx: Context, writer: JsonlWriter) -> None:
    target = ctx.settings["generate"]["answers"]["wikipedia"]
    tests = ctx.tests()
    exclude = {normalize(p) for p in (tests.get("wiki") or {}).values()}
    test_data = ctx.test_data()
    if test_data.exists():
        import yaml

        snapshot = yaml.safe_load(test_data.read_text(encoding="utf-8")) or {}
        exclude |= {normalize(w.get("title", "")) for w in (snapshot.get("wiki") or {}).values()}
    # the first titles ask the router's knowledge questions - the summaries use the next ones
    skip = ctx.settings["generate"]["router"]["knowledge"] * 2
    titles = wikipedia_titles(ctx.ws.generated / "wiki_titles.json", skip + target * 3, exclude)
    titles = titles[skip:]
    teacher = ctx.teacher()
    holdout = ctx.holdout()
    key = ctx.pack.QUESTIONS_KEY
    sentences = ctx.config.sentences
    rejected = 0
    for start in range(0, len(titles), WIKI_BATCH):
        if writer.count("wikipedia") >= target:
            break
        batch = [
            t
            for t in titles[start : start + WIKI_BATCH]
            if ("wikipedia", f"wiki:{t}") not in writer.seen
        ]
        if not batch:
            continue
        reply = teacher.json(
            [{"role": "user", "content": ctx.pack.wiki_question_prompt(batch)}],
            list_schema(key),
            temperature=0.5,
            num_predict=800,
            num_ctx=4096,
        )
        for title, question in zip(batch, sentences_of(reply, key), strict=False):
            if holdout.match(question):
                rejected += 1
                continue
            try:
                found, article = ctx.integ.snapshot_data.wikipedia(
                    question, ctx.config.wikipedia_language
                )
            except (OSError, KeyError, StopIteration):
                continue
            if normalize(found) in exclude or len(article) < 300:
                continue
            messages = ctx.integ.summary_messages(ctx.config, article, question)
            answer = teacher.text(
                messages, temperature=0.2, num_predict=SUMMARY_TOKENS_PER_SENTENCE * sentences
            )
            if form_problems(answer, 2, sentences + 1):
                rejected += 1
                continue
            writer.write(
                {
                    "role": "answers",
                    "part": "wikipedia",
                    "id": f"wiki:{title}",
                    "text": question,
                    "messages": messages,
                    "answer": answer,
                    "source": "teacher",
                }
            )
        progress("answers", "wikipedia", writer.count("wikipedia"), target, rejected)


def generate(ctx: Context, parts: tuple[str, ...] = ("given", "live", "wikipedia")) -> Any:
    """Write workspace/generated/answers.jsonl (resumable)."""
    stage("answers")
    out = ctx.ws.generated / "answers.jsonl"
    with JsonlWriter(out, key=_key, group=lambda row: row["part"].split(":")[0]) as writer:
        steps = {"given": given, "live": live, "wikipedia": wikipedia}
        for part in parts:
            steps[part](ctx, writer)
    return out
