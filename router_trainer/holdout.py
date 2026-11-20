"""The frozen test: no training sentence may equal or nearly equal a test sentence.

The test (``model_test.yaml``) is the only measure of a trained model, so its questions,
commands and Wikipedia topics never get into training - not even slightly reworded. A training
sentence is dropped when, after normalization (lower case, no accents or punctuation), it is
the same as a test sentence, or close to one by word stems or by character trigrams.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

STEM = 5  # crude stemming for an inflected language: the first letters of a word


# letters with a stroke that Unicode does not split into a letter and an accent
_STROKES = str.maketrans("łŁøØđĐħĦ", "lLoOdDhH")


def strip_accents(text: str) -> str:
    """„Zażółć” -> „Zazolc”, „Příliš” -> „Prilis” - for any language with Latin letters."""
    text = unicodedata.normalize("NFKD", str(text).translate(_STROKES))
    return unicodedata.normalize("NFC", "".join(c for c in text if not unicodedata.combining(c)))


def normalize(text: str) -> str:
    """Lower case, no accents, no punctuation, single spaces."""
    text = strip_accents(str(text).lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def stems(text: str) -> frozenset[str]:
    return frozenset(word[:STEM] for word in normalize(text).split())


def trigrams(text: str) -> frozenset[str]:
    padded = f" {normalize(text)} "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def test_sentences(tests: dict[str, Any]) -> list[str]:
    """Every sentence of the test file: router questions, control commands, answer questions
    and the Wikipedia phrases (their articles are not used for training either)."""
    out: list[str] = []
    for row in tests.get("router") or []:
        out.append(str(row[0]))
    for case in (tests.get("control") or {}).get("cases") or []:
        out.append(str(case["text"]))
    for section in ("answers", "real", "wiki_answers"):
        for case in (tests.get(section) or {}).get("cases") or []:
            out.append(str(case["question"]))
    out.extend(str(phrase) for phrase in (tests.get("wiki") or {}).values())
    return [s for s in dict.fromkeys(out) if s.strip()]


@dataclass
class _Entry:
    text: str
    stems: frozenset[str]
    trigrams: frozenset[str]


@dataclass
class Holdout:
    """Matcher of training sentences against the frozen test."""

    sentences: list[str]
    word_similarity: float = 0.8
    char_similarity: float = 0.85
    _exact: dict[str, str] = field(init=False, default_factory=dict)
    _entries: list[_Entry] = field(init=False, default_factory=list)
    _index: dict[str, list[int]] = field(init=False, default_factory=lambda: defaultdict(list))

    def __post_init__(self) -> None:
        for text in self.sentences:
            key = normalize(text)
            if not key:
                continue
            self._exact.setdefault(key, text)
            entry = _Entry(text, stems(text), trigrams(text))
            for stem in entry.stems:
                self._index[stem].append(len(self._entries))
            self._entries.append(entry)

    def match(self, text: str) -> str | None:
        """The test sentence ``text`` collides with, or None."""
        key = normalize(text)
        if not key:
            return None
        if key in self._exact:
            return self._exact[key]
        own_stems, own_trigrams = stems(text), trigrams(text)
        candidates = {i for stem in own_stems for i in self._index.get(stem, ())}
        for i in candidates:
            entry = self._entries[i]
            if jaccard(own_stems, entry.stems) >= self.word_similarity:
                return entry.text
            if jaccard(own_trigrams, entry.trigrams) >= self.char_similarity:
                return entry.text
        return None

    def split(self, texts: Iterable[str]) -> tuple[list[str], list[tuple[str, str]]]:
        """(kept, rejected as (sentence, test sentence))."""
        kept, rejected = [], []
        for text in texts:
            hit = self.match(text)
            if hit is None:
                kept.append(text)
            else:
                rejected.append((text, hit))
        return kept, rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentences": self.sentences,
            "word_similarity": self.word_similarity,
            "char_similarity": self.char_similarity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Holdout:
        return cls(data["sentences"], data["word_similarity"], data["char_similarity"])


def freeze(tests: dict[str, Any], settings: dict[str, Any], out: Path) -> Holdout:
    """Write the frozen test sentences (workspace/holdout/holdout.json)."""
    holdout = Holdout(
        test_sentences(tests),
        float(settings["holdout"]["word_similarity"]),
        float(settings["holdout"]["char_similarity"]),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(holdout.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return holdout


def load(path: Path) -> Holdout:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - freeze the test first (router-trainer freeze)")
    return Holdout.from_dict(json.loads(path.read_text(encoding="utf-8")))
