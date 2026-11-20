"""Shared by the generators: resumable JSONL files, speech-recognition noise, progress lines.

Every generator appends rows to ``workspace/generated/<role>.jsonl`` and skips what is already
there, so a stopped generation continues where it ended. Progress is printed as
``@@progress {...}`` lines, which the panel reads from the log.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import re
from typing import Any

from ..holdout import normalize, strip_accents

PROGRESS = "@@progress"


def progress(role: str, part: str, done: int, target: int, rejected: int = 0) -> None:
    line = {"role": role, "part": part, "done": done, "target": target, "rejected": rejected}
    print(f"{PROGRESS} {json.dumps(line, ensure_ascii=False)}", flush=True)


def stage(name: str) -> None:
    print(f"==> {name}", flush=True)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # a line cut by a stop


def _text_key(row: dict[str, Any]) -> tuple[Any, str]:
    return row.get("part"), normalize(row["text"])


def _part(row: dict[str, Any]) -> str:
    return row.get("part", "")


class JsonlWriter:
    """Appends rows; ``seen`` holds the keys of rows written before (resume), ``count`` the
    rows per group (by default the row's ``part``)."""

    def __init__(self, path: Path, key=_text_key, group=_part):
        self.path = path
        self.key = key
        self.group = group
        path.parent.mkdir(parents=True, exist_ok=True)
        self.seen: set[Any] = set()
        self.counts: dict[str, int] = {}
        for row in read_jsonl(path):
            self.seen.add(key(row))
            self.counts[group(row)] = self.counts.get(group(row), 0) + 1
        self._handle = path.open("a", encoding="utf-8")

    def count(self, group: str) -> int:
        return self.counts.get(group, 0)

    def write(self, row: dict[str, Any]) -> bool:
        key = self.key(row)
        if key in self.seen:
            return False
        self.seen.add(key)
        self.counts[self.group(row)] = self.counts.get(self.group(row), 0) + 1
        self._handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._handle.flush()
        return True

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --- requests side by side ------------------------------------------------------------------


def in_parallel(function: Callable[[Any], Any], items: list[Any], workers: int) -> list[Any]:
    """``function`` for every item, ``workers`` at a time (the teacher's Ollama slots); the
    results in the order of the items, so a resumed run writes the same rows."""
    if workers <= 1 or len(items) <= 1:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(function, items))


# --- speech recognition noise ---------------------------------------------------------------


def noisy(text: str, rng: random.Random) -> str:
    """One kind of noise as from speech recognition or typing."""
    words = text.split()
    roll = rng.random()
    if roll < 0.25:
        return text.lower()
    if roll < 0.4:
        return strip_accents(text)  # no accents, as typed in a hurry
    if roll < 0.55 and words and len(words[0]) > 2:
        words[0] = words[0][:2].upper() + words[0][2:]  # „JAkie” - Shift held
        return " ".join(words)
    if roll < 0.8 and words:
        i = rng.randrange(len(words))
        word = words[i]
        if len(word) > 4:
            j = rng.randrange(1, len(word) - 1)
            words[i] = rng.choice(
                [
                    word[:j] + word[j + 1 :],
                    word[:j] + word[j] + word[j:],
                    word[: j - 1] + word[j] + word[j - 1] + word[j + 1 :],
                ]
            )
        return " ".join(words)
    return re.sub(r"[?.!,]", "", text)


def tidy(text: str, rng: random.Random) -> str:
    """As speech recognition writes: a capital first letter and (usually) an end mark."""
    text = " ".join(str(text).split())
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if rng.random() < 0.8 and not text.endswith(("?", ".", "!")):
        text += "?" if rng.random() < 0.7 else "."
    return text


def strip_speaker(text: str) -> str:
    """Models sometimes write the speaker („Kuba: …”); speech recognition never does."""
    text = str(text).strip()
    found = re.match(r"([^\W\d_]\w{1,12}):\s*", text)
    return text[found.end() :].strip() if found and found[1][0].isupper() else text


def sample(items: Iterable[Any], k: int, rng: random.Random) -> list[Any]:
    items = list(items)
    return rng.sample(items, min(k, len(items)))


def list_schema(key: str) -> dict[str, Any]:
    """JSON schema of a teacher reply with a list of sentences under ``key``."""
    return {
        "type": "object",
        "properties": {key: {"type": "array", "items": {"type": "string"}}},
        "required": [key],
    }


def sentences_of(reply: dict[str, Any] | None, key: str) -> list[str]:
    """Sentences from a teacher reply in ``list_schema(key)``."""
    if not reply:
        return []
    values = reply.get(key) or []
    return [strip_speaker(s) for s in values if isinstance(s, str) and strip_speaker(s)]
