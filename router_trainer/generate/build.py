"""Dataset: generated rows -> chats in the integration's format, checked and split.

Each example is the exact chat the integration sends (system + user) plus the answer the
model should give. On the way:
- the frozen test is checked once more (exact and near duplicates are dropped and listed);
- router topics are capped and small topics padded with noisy variants;
- duplicates are removed, each role is sampled by ``dataset.mix``;
- the dev part (eval loss during training) is chosen by a hash of the user text, so the same
  sentence is always on the same side, also after rebuilding with more data.

Output: workspace/datasets/<name>/train.jsonl, dev.jsonl and card.json.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from ..context import Context
from ..holdout import normalize
from .common import noisy, read_jsonl, stage, tidy

HOLDOUT_SAMPLES = 40


def is_dev(text: str, fraction: float) -> bool:
    digest = hashlib.sha1(normalize(text).encode()).hexdigest()
    return int(digest[:8], 16) % 10_000 < fraction * 10_000


def router_rows(
    ctx: Context, rng: random.Random, rejected: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Router chats; generated sentences like a test sentence are dropped *before* padding
    and noise (a noisy copy of a test sentence could slip past the check)."""
    settings = ctx.settings["generate"]["router"]
    holdout = ctx.holdout()
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    from ..teacher import is_manual
    from . import labels

    # judged by hand: a checked sentence without its topic yet waits outside the dataset
    waiting_for = None
    if is_manual(ctx.settings, "judge"):
        waiting_for = (labels.Checker(ctx, label=lambda text: None), labels.checked_sources(ctx))
    waiting = 0
    for row in read_jsonl(ctx.ws.generated / "router.jsonl"):
        if row["topic"] not in ctx.config.topics:
            continue
        checker, sources = waiting_for or (None, ())
        if checker and row.get("source") in sources and not checker.known(row["text"]):
            waiting += 1
            continue
        hit = holdout.match(row["text"])
        if hit:
            if rejected is not None:
                rejected.append({"role": "router", "text": row["text"], "test": hit})
            continue
        by_topic[row["topic"]].append(row)
    if waiting:
        print(
            f"router: {waiting} sentences wait for the judge (router-trainer handoff)", flush=True
        )
    out = []
    for topic, rows in by_topic.items():
        rng.shuffle(rows)
        # natural sentences first (teacher, log, examples), then templates and intents
        rows.sort(key=lambda r: r["source"] in ("trigger", "intent"))
        rows = rows[: settings["max_per_topic"]]
        padded = list(rows)
        while padded and len(padded) < settings["min_per_topic"]:
            base = rng.choice(rows)
            padded.append(
                {**base, "text": noisy(base["text"], rng), "source": base["source"] + "+noise"}
            )
        for row in padded:
            text = tidy(row["text"], rng)
            if rng.random() < settings["noise"]:
                text = noisy(text, rng)
            out.append(
                {
                    "role": "router",
                    "topic": topic,
                    "source": row["source"],
                    "text": text,
                    "messages": [
                        *ctx.integ.router_messages(ctx.config, text),
                        {"role": "assistant", "content": ctx.integ.router_answer(topic)},
                    ],
                }
            )
    return out


def control_rows(ctx: Context, home_data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in read_jsonl(ctx.ws.generated / "control.jsonl"):
        messages = ctx.integ.control_messages(home_data, ctx.config.household, row["text"])
        out.append(
            {
                "role": "control",
                "topic": row["part"],
                "source": row["source"],
                "text": row["text"],
                "messages": [*messages, {"role": "assistant", "content": row["answer"]}],
            }
        )
    return out


def answer_rows(ctx: Context) -> list[dict[str, Any]]:
    out = []
    for row in read_jsonl(ctx.ws.generated / "answers.jsonl"):
        out.append(
            {
                "role": "answers",
                "topic": row["part"],
                "source": row["source"],
                "text": row["text"],
                "messages": [*row["messages"], {"role": "assistant", "content": row["answer"]}],
            }
        )
    return out


ROLES = ("router", "control", "answers")


def build(ctx: Context, name: str, roles: tuple[str, ...] = ROLES) -> Path:
    """``roles`` - the roles the model will play; the others are left out of the dataset (a
    model that only chooses the topic needs no commands or answers)."""
    stage("dataset")
    rng = ctx.rng("dataset")
    holdout = ctx.holdout()
    home_data = ctx.home_data()
    mix = {**ctx.settings["dataset"]["mix"], **{r: 0.0 for r in ROLES if r not in roles}}
    fraction = float(ctx.settings["dataset"]["dev_fraction"])

    rejected: list[dict[str, Any]] = []
    rows = router_rows(ctx, rng, rejected) + control_rows(ctx, home_data) + answer_rows(ctx)
    kept, seen = [], set()
    for row in rows:
        key = (row["role"], normalize(row["text"]))
        if key in seen:
            continue
        seen.add(key)
        hit = holdout.match(row["text"])
        if hit:
            rejected.append({"role": row["role"], "text": row["text"], "test": hit})
            continue
        kept.append(row)
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in kept:
        by_role[row["role"]].append(row)
    chosen = []
    for role, role_rows in by_role.items():
        share = float(mix.get(role, 1.0))
        rng.shuffle(role_rows)
        chosen += role_rows[: round(len(role_rows) * share)]
    rng.shuffle(chosen)
    train = [r for r in chosen if not is_dev(r["text"], fraction)]
    dev = [r for r in chosen if is_dev(r["text"], fraction)]

    folder = ctx.ws.dataset(name)
    folder.mkdir(parents=True, exist_ok=True)
    for part, part_rows in (("train", train), ("dev", dev)):
        with (folder / f"{part}.jsonl").open("w", encoding="utf-8") as handle:
            for row in part_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    card = {
        "name": name,
        "created": datetime.now().isoformat(timespec="minutes"),
        "fingerprint": ctx.integ.fingerprint(ctx.config, home_data),
        "train": len(train),
        "dev": len(dev),
        "roles": dict(Counter(r["role"] for r in chosen)),
        "sources": dict(Counter(f"{r['role']}/{r['source']}" for r in chosen)),
        "topics": dict(Counter(f"{r['role']}/{r['topic']}" for r in chosen)),
        "holdout_rejected": len(rejected),
        "holdout_samples": rejected[:HOLDOUT_SAMPLES],
        "settings": {key: ctx.settings[key] for key in ("generate", "holdout", "dataset")},
    }
    (folder / "card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"dataset {name}: train {len(train)}, dev {len(dev)}, roles {card['roles']}, "
        f"dropped as like a test sentence {len(rejected)}",
        flush=True,
    )
    return folder
