"""Router labels that agree with router.yaml, and examples on the borders of the topics.

The teacher writing paraphrases sees one topic at a time, so it sometimes writes a sentence that
router.yaml puts elsewhere: „Puść podcast w kuchni” for ``media`` although its description says
„polecenie puść lub uruchom to sterowanie”. A small model learns exactly that mistake. Two fixes:

- **Label check**: every teacher sentence is read once more by the teacher *with the router's own
  prompt* (all topics and their descriptions, as Home Assistant asks it). A sentence it puts in
  another topic is dropped; its Whisper copies (``asr``) go with it. The answers are kept in
  ``generated/labels.json``, the dropped rows in ``generated/labels_dropped.jsonl`` for review.
- **Contrast**: for pairs of topics that get confused, the teacher writes sentences on both sides
  of the border (same words, rooms and devices, different topic). Each one has to pass the label
  check. The pairs come from ``contrast.pairs`` or, with ``auto``, from the errors of the last
  evaluations (``runs/*/eval.json``) - of the trained models and of the baseline.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import Any

from ..context import Context
from ..holdout import Holdout, normalize
from ..teacher import PARALLEL, is_manual
from .common import JsonlWriter, in_parallel, progress, read_jsonl, sentences_of, stage

SAVE_EVERY = 20
CONTRAST_BATCH = 12
# „text -> got (expected a / b)” - a router error line of eval.json
ERROR = re.compile(r" -> (?P<got>\S+) \(expected (?P<expected>[^)]+)\)$")


def labeler(ctx: Context) -> Callable[[str], str | None]:
    """The teacher's topic for one sentence, asked with the router's own prompt."""
    teacher = ctx.teacher("judge")
    schema = ctx.integ.router_schema(ctx.config)

    def label(text: str) -> str | None:
        reply = teacher.json(ctx.integ.router_messages(ctx.config, text), schema, num_predict=30)
        topic = (reply or {}).get(ctx.integ.lang.TOPIC_KEY)
        return topic if topic in ctx.config.topics else None

    return label


class Checker:
    """The judge's topics of sentences, asked once (cached in generated/labels.json). With the
    judge done by hand (``teacher.judge.provider: manual``) nothing is asked: the sentences wait
    in generated/handoff/judge-pending.json for router-trainer handoff export judge."""

    def __init__(self, ctx: Context, label: Callable[[str], str | None] | None = None) -> None:
        self.path = ctx.ws.generated / "labels.json"
        self.pending_path = ctx.ws.generated / "handoff" / "judge-pending.json"
        self.cache: dict[str, str] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        )
        self.manual = label is None and is_manual(ctx.settings, "judge")
        self.label = label or (None if self.manual else labeler(ctx))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), "utf-8")

    def ask(self, texts: list[str], show: bool = False) -> None:
        missing = list(dict.fromkeys(t for t in texts if normalize(t) not in self.cache))
        if self.label is None:  # judged by hand: the sentences wait for the handoff
            self.wait(missing)
            return
        for first in range(0, len(missing), SAVE_EVERY):
            part = missing[first : first + SAVE_EVERY]
            for text, topic in zip(part, in_parallel(self.label, part, PARALLEL), strict=True):
                self.cache[normalize(text)] = topic or ""
            self.save()
            if show:
                progress("router", "labels", first + len(part), len(missing))

    def wait(self, texts: list[str]) -> None:
        if not texts:
            return
        waiting = (
            json.loads(self.pending_path.read_text(encoding="utf-8"))
            if self.pending_path.is_file()
            else []
        )
        waiting = list(dict.fromkeys([*waiting, *texts]))
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(waiting, ensure_ascii=False, indent=0), "utf-8")

    def known(self, text: str) -> bool:
        return normalize(text) in self.cache

    def topic(self, text: str) -> str:
        """The teacher's topic, "" when it gave none."""
        return self.cache.get(normalize(text), "")

    def agrees(self, text: str, topic: str) -> bool:
        """No answer counts as agreeing - only a clear other topic drops a sentence."""
        got = self.topic(text)
        return not got or got == topic


def checked_sources(ctx: Context) -> tuple[str, ...]:
    setting = ctx.settings["generate"]["router"].get("check_labels", True)
    if setting is True:
        return ("paraphrase", "contrast", "external")
    if not setting:
        return ()
    return tuple(setting)


def clean(ctx: Context, checker: Checker) -> int:
    """Drop the rows of router.jsonl whose topic the teacher puts elsewhere (and their Whisper
    copies). Run before the writer opens the file; the paraphrases refill what was dropped."""
    sources = checked_sources(ctx)
    path = ctx.ws.generated / "router.jsonl"
    if not sources or not path.is_file():
        return 0
    rows = list(read_jsonl(path))
    checked = [r for r in rows if r.get("source") in sources]
    if not checked:
        return 0
    stage("router labels")
    checker.ask([r["text"] for r in checked], show=True)
    wrong = [r for r in checked if not checker.agrees(r["text"], r["topic"])]
    gone = {normalize(r["text"]) for r in wrong}
    kept = [
        r
        for r in rows
        if normalize(r["text"]) not in gone
        or r.get("source") not in sources  # the same text from another source stays
    ]
    kept = [r for r in kept if not (r.get("spoken") and normalize(r["spoken"]) in gone)]
    moved = Counter(f"{r['topic']} -> {checker.topic(r['text'])}" for r in wrong)
    print(
        f"labels: {len(checked)} checked, {len(wrong)} in another topic"
        + "".join(f"\n  {n:4}  {pair}" for pair, n in moved.most_common(15)),
        flush=True,
    )
    if len(kept) == len(rows):
        return 0
    with (ctx.ws.generated / "labels_dropped.jsonl").open("a", encoding="utf-8") as handle:
        for row in wrong:
            handle.write(
                json.dumps({**row, "teacher": checker.topic(row["text"])}, ensure_ascii=False)
                + "\n"
            )
    temporary = path.with_suffix(".jsonl.tmp")
    temporary.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8"
    )
    temporary.replace(path)
    return len(rows) - len(kept)


# --- contrast: both sides of a border ------------------------------------------------------------


def confusions(runs: Path) -> list[tuple[str, str]]:
    """Pairs of topics mixed up in the evaluations (runs/*/eval.json), most frequent first."""
    counts: Counter[tuple[str, str]] = Counter()
    for file in sorted(runs.glob("*/eval.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for result in data.values() if isinstance(data, dict) else []:
            for error in ((result or {}).get("router") or {}).get("errors") or []:
                found = ERROR.search(str(error))
                if not found:
                    continue
                got = found["got"]
                for expected in found["expected"].split(" / "):
                    if expected.strip() != got:
                        counts[tuple(sorted((expected.strip(), got)))] += 1
    return [pair for pair, _ in counts.most_common()]


def contrast_pairs(ctx: Context) -> list[tuple[str, str]]:
    setting = ctx.settings["generate"]["router"].get("contrast") or {}
    pairs = setting.get("pairs", "auto")
    if pairs == "auto":
        pairs = confusions(ctx.ws.runs)[: int(setting.get("max_pairs", 12))]
    # extra: pairs always added (e.g. a new topic that has no evaluation errors yet), first
    extra = setting.get("extra") or []
    out: list[tuple[str, str]] = []
    for pair in [*extra, *(pairs or [])]:
        first, second = sorted(str(p) for p in pair)
        known = first != second and {first, second} <= set(ctx.config.topics)
        if known and (first, second) not in out:
            out.append((first, second))
    return out


def contrast_schema(keys: tuple[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: {"type": "array", "items": {"type": "string"}} for k in keys},
        "required": list(keys),
    }


def contrast(
    ctx: Context, writer: JsonlWriter, holdout: Holdout, checker: Checker, home_data: dict
) -> None:
    setting = ctx.settings["generate"]["router"].get("contrast") or {}
    target = int(setting.get("per_side", 0))
    pairs = contrast_pairs(ctx)
    if not target or not pairs:
        return
    stage("router contrast")
    print("contrast: " + ", ".join(f"{a}/{b}" for a, b in pairs), flush=True)
    from .router import topic_hint

    pack = ctx.pack
    rng = ctx.rng("contrast")
    teacher = ctx.teacher("writer")
    keys = pack.CONTRAST_KEYS
    schema = contrast_schema(keys)
    for pair in pairs:
        topics = [ctx.config.topics[name] for name in pair]
        parts = [f"contrast:{pair[0]}|{pair[1]}:{name}" for name in pair]
        tries, rejected = 0, 0
        limit = max(3, -(-target // CONTRAST_BATCH) * 3)
        while min(writer.count(p) for p in parts) < target and tries < limit:
            tries += 1
            prompt = pack.contrast_prompt(
                ctx.config.household,
                [(t.name, t.description, list(t.examples)) for t in topics],
                CONTRAST_BATCH,
                pack.STYLES[tries % len(pack.STYLES)],
                topic_hint(ctx, topics[rng.randrange(2)], home_data, rng),
            )
            reply = teacher.json(
                [{"role": "user", "content": prompt}],
                schema,
                temperature=1.0,
                num_predict=1500,
                seed=rng.randrange(1 << 30),
            )
            written: dict[str, list[str]] = defaultdict(list)
            for key, topic in zip(keys, topics, strict=True):
                written[topic.name] = [t for t in sentences_of(reply, key) if not holdout.match(t)]
            checker.ask([t for texts in written.values() for t in texts])
            for topic_name, part in zip(pair, parts, strict=True):
                for text in written[topic_name]:
                    if checker.topic(text) != topic_name:  # a border sentence needs a clear yes
                        rejected += 1
                        continue
                    writer.write(
                        {
                            "role": "router",
                            "part": part,
                            "text": text,
                            "topic": topic_name,
                            "source": "contrast",
                        }
                    )
            progress("router", f"contrast:{pair[0]}|{pair[1]}",
                     min(writer.count(p) for p in parts), target, rejected)  # fmt: skip
