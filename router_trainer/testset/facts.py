"""Facts a good answer must (not) contain, as the test's regular expressions.

The judge points at short facts in the data or the article; a fact is kept only when it is
literally there (a made-up fact would test the judge, not the model). Facts become patterns
that accept the usual spoken forms: ``17:00`` -> ``17[:.]00``, ``205`` -> ``\\b205\\b``, a word ->
its first letters (inflection: „basen”, „basenie”, „basenu”).
"""

from __future__ import annotations

import re

from ..holdout import normalize

STEM = 5
TIME = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
NUMBER = re.compile(r"^\d+([.,]\d+)?$")
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
YEAR = re.compile(r"^(19|20)\d\d$")
# raw Home Assistant states: an answer says them in words („słonecznie”), never like this
_STATES = (
    "on off home not_home open closed opening closing locked unlocked unavailable unknown idle "
    "playing paused standby heat cool auto dry fan_only docked cleaning returning charging true "
    "false sunny cloudy partlycloudy rainy pouring snowy snowy-rainy fog hail windy windy-variant "
    "lightning lightning-rainy clear-night exceptional"
)
RAW_STATES = frozenset(_STATES.split())


def usable(fact: str, source: str = "") -> bool:
    """Not a raw HA state or an attribute name of the data („savings: 20”) - the answer says
    them in its own words - and not a lone digit („1” matches almost anything)."""
    fact = fact.strip(" .,;:!?\"'„”")
    if normalize(fact).replace(" ", "_") in RAW_STATES or re.fullmatch(r"\d", fact):
        return False
    return not (source and re.search(rf"(?<![\w-]){re.escape(fact)}\s*:", source))


def in_source(fact: str, source: str) -> bool:
    fact = normalize(fact)
    return bool(fact) and fact in normalize(source)


def _number(digits: str) -> str | None:
    """A whole number; not a year (answers leave it out) and not a lone digit (ambiguous)."""
    if YEAR.match(digits) or len(digits) == 1:
        return None
    if len(digits) >= 4:  # „156317” is also said „156 317”
        return rf"\b{digits[:-3]}\s?{digits[-3:]}\b"
    return rf"\b{digits}\b"


def pattern(fact: str, stem: int = STEM, swaps: dict[str, str] | None = None) -> str | None:
    """A regular expression on the lower-cased answer, or None for an unusable fact."""
    fact = " ".join(str(fact).split()).strip(" .,;:!?\"'„”")
    if not fact:
        return None
    if match := TIME.match(fact):
        hour, minute = int(match.group(1)), match.group(2)
        # „7:30”, „07:30”; „5,48” too - a time-like fact may be a decimal (an average)
        return rf"\b0?{hour}[:.,]{minute}\b"
    if NUMBER.match(fact):
        if "." in fact or "," in fact:
            return re.escape(fact.replace(",", ".")).replace(r"\.", "[.,]")
        return _number(fact)
    words = [w.lower() for w in WORD.findall(fact)]
    if not words:
        digits = re.findall(r"\d+", fact)  # „156317 km”, „2026 r.”
        return _number(digits[0]) if digits else None
    # the longest word carries the meaning („wizyta u dentysty” -> „denty”)
    word = max(words, key=len)
    return stem_pattern(word[:stem] if len(word) > stem else word, swaps)


def stem_pattern(stem: str, swaps: dict[str, str] | None = None) -> str:
    """A word's stem as a pattern; ``swaps`` - letters inflection changes (the language pack's
    ``INFLECTION_SWAPS``, in Polish „pokój” / „pokoju”: ``{"ó": "[óo]", …}``)."""
    return "".join((swaps or {}).get(c, re.escape(c)) for c in stem)


def required(patterns: list[str]) -> list:
    """The test's ``must`` from the judge's facts: at least one of them (a list in the list).
    A broad question („how is my day?”) has several right answers - each names some facts."""
    if not patterns:
        return []
    return [patterns[0]] if len(patterns) == 1 else [list(patterns)]


def to_patterns(
    facts: list[str],
    source: str,
    limit: int = 3,
    forbidden: bool = False,
    question: str = "",
    generic: frozenset[str] = frozenset(),
    stem: int = STEM,
    swaps: dict[str, str] | None = None,
) -> list[str]:
    """Patterns of the facts that are literally in ``source`` (at most ``limit``; facts with
    digits first - they test the most). Left out: raw HA states, facts the question already
    says (any answer repeats them), generic words (``generic``: stems like „roku”) and, among
    years (answers usually give a date without one)."""
    out: list[str] = []
    asked = question.lower()
    ordered = sorted(
        (f for f in facts if isinstance(f, str)), key=lambda f: not re.search(r"\d", f)
    )
    for fact in ordered:
        if not in_source(fact, source) or not usable(fact, source):
            continue
        if YEAR.match(fact.strip(" .,;:!?")):
            continue  # answers usually give a date without the year
        made = pattern(fact, stem, swaps)
        if not made or made in out or made in {stem_pattern(g, swaps) for g in generic}:
            continue
        if asked and re.search(made, asked):
            continue
        out.append(made)
        if len(out) >= limit:
            break
    return out
