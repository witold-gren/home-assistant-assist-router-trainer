"""Polish trainer pack (pl): grammar.

The functions that fill the prompt templates of texts.yaml and build made-up data for answers
(given_scenario: dates, sums, lessons - they depend on grammar). This file runs with every name of
texts.yaml and words.yaml already defined. For a new language: keep the names and arguments of the
functions; the prompt wrappers need no change, given_scenario needs its sentences translated.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import random
from typing import Any

# =====================================================================================
# Router: paraphrases written by the teacher
# =====================================================================================


def _json(*keys: str, lists: tuple[str, ...] = ()) -> str:
    """The answer format of a prompt: {"zdania": [...]} (a list per key)."""
    items = lists or ("[...]",) * len(keys)
    return (
        "{" + ", ".join(f'"{key}": {value}' for key, value in zip(keys, items, strict=True)) + "}"
    )


def _examples(examples: list[str]) -> str:
    return "; ".join(examples) if examples else NO_EXAMPLES


def paraphrase_prompt(
    household: str,
    topic: str,
    description: str,
    examples: list[str],
    count: int,
    style: str,
    hint: str,
) -> str:
    return PARAPHRASE_PROMPT.format(
        household=household, count=count, topic=topic, description=description,
        examples=_examples(examples), hint=hint, style=style, json=_json(SENTENCES_KEY),
    )  # fmt: skip


def contrast_prompt(
    household: str,
    topics: list[tuple[str, str, list[str]]],
    count: int,
    style: str,
    hint: str,
) -> str:
    (a, a_text, a_examples), (b, b_text, b_examples) = topics
    lists = (CONTRAST_LIST.format(topic=a), CONTRAST_LIST.format(topic=b))
    return CONTRAST_PROMPT.format(
        household=household, a=a, a_description=a_text, a_examples=_examples(a_examples),
        b=b, b_description=b_text, b_examples=_examples(b_examples), count=count, hint=hint,
        style=style, json=_json(*CONTRAST_KEYS, lists=lists),
    )  # fmt: skip


def hint_other(others: str) -> str:
    return HINT_OTHER.format(others=others)


def hint_control(areas: str, devices: str) -> str:
    return HINT_CONTROL.format(areas=areas, devices=devices)


def hint_rooms(areas: str) -> str:
    return HINT_ROOMS.format(areas=areas)


def knowledge_prompt(titles: list[str]) -> str:
    """One natural question per encyclopedia title (grammatical forms by the teacher)."""
    return KNOWLEDGE_PROMPT.format(titles="; ".join(titles), json=_json(QUESTIONS_KEY))


def command_prompt(details: list[str], count: int, style: str) -> str:
    return COMMAND_PROMPT.format(
        count=count, details="; ".join(details), style=style, json=_json(SENTENCES_KEY)
    )


def _date(day: datetime) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day}.{day.month:02d}"


def _stem(text: str) -> str:
    return text.lower().split()[0][:5]


def given_scenario(rng: random.Random, now: datetime, names: list[str]) -> dict[str, Any]:
    """Made-up data, a question and the facts a good answer must (not) have.

    ``names`` - people of the household (from router.yaml), so the data sound like home.
    Returns {kind, data, question, must, never}; ``must``/``never`` are regular expressions
    on the lower-cased answer (like the test's).
    """
    people = names or ["Ola", "Kuba", "Ewa"]
    kind = rng.choice(["sum", "tomorrow", "minutes", "lessons", "unknown", "car", "chores"])
    if kind == "sum":
        chosen = rng.sample(people, min(3, len(people)))
        amounts = [rng.randrange(5, 300, 5) for _ in chosen]
        lines = ", ".join(f"{n} {a} zł" for n, a in zip(chosen, amounts, strict=True))
        return {
            "kind": kind,
            "data": f"Stan kont kieszonkowego: {lines}.",
            "question": rng.choice(
                [
                    "Ile pieniędzy mają razem?",
                    "Ile razem jest na kontach kieszonkowego?",
                    "Jaka jest suma kieszonkowego wszystkich?",
                ]
            ),
            "must": [rf"\b{sum(amounts)}\b"],
            "never": [],
        }
    if kind == "tomorrow":
        person = rng.choice(people)
        events = rng.sample(EVENTS, 4)
        days = [now + timedelta(days=d) for d in (0, 1, 2, 3)]
        hours = [f"{rng.randrange(8, 20)}:{rng.choice(['00', '15', '30', '45'])}" for _ in days]
        lines = "; ".join(
            f"{_date(d)} - {h} {e}" for d, h, e in zip(days, hours, events, strict=True)
        )
        return {
            "kind": kind,
            "data": f"Kalendarz - {person} (najbliższe dni): {lines}.",
            "question": rng.choice(
                [
                    f"Co {person} ma jutro?",
                    f"Jakie {person} ma jutro plany?",
                    f"Co jest jutro w kalendarzu u {person}?",
                ]
            ),
            "must": [_stem(events[1]), hours[1].replace(":", "[:.]")],
            "never": [_stem(e) for i, e in enumerate(events) if i != 1],
        }
    if kind == "minutes":
        event = rng.choice(EVENTS)
        start = now.replace(second=0, microsecond=0)
        minutes = rng.randrange(10, 95, 5)
        at = start + timedelta(minutes=minutes)
        return {
            "kind": kind,
            "data": f"Kalendarz dziś: {at.hour}:{at.minute:02d} {event}.",
            "question": rng.choice(
                [
                    f"Za ile minut zaczyna się wydarzenie „{event}”?",
                    f"Ile zostało czasu do: {event}?",
                ]
            ),
            "must": [rf"\b{minutes}\b|godzin"],
            "never": [],
            "now": start.isoformat(),
        }
    if kind == "lessons":
        person = rng.choice(people)
        day = now + timedelta(days=1)
        count = rng.randrange(4, 8)
        subjects = rng.sample(LESSONS, count)
        plan = ", ".join(
            f"{i + 1}. {LESSON_TIMES[i][0]}-{LESSON_TIMES[i][1]} {s}"
            for i, s in enumerate(subjects)
        )
        return {
            "kind": kind,
            "data": f"Plan lekcji - {person}, {_date(day)}: {plan}.",
            "question": rng.choice(
                [
                    f"O której {person} jutro kończy lekcje?",
                    f"Kiedy {person} wychodzi jutro ze szkoły?",
                ]
            ),
            "must": [LESSON_TIMES[count - 1][1].replace(":", "[:.]")],
            "never": [LESSON_TIMES[count - 2][1].replace(":", "[:.]") + r"(?!\d)"],
        }
    if kind == "unknown":
        return {
            "kind": kind,
            "data": f"Temperatura na zewnątrz {rng.randrange(-5, 30)} °C. W domu: "
            + ", ".join(rng.sample(people, min(2, len(people))))
            + ".",
            "question": rng.choice(UNKNOWN_QUESTIONS),
            "must": [NEGATIVE],
            "never": [],
        }
    if kind == "car":
        km, litres, total = (
            rng.randrange(80, 900),
            rng.randrange(5, 70),
            rng.randrange(20, 300) * 1000,
        )
        return {
            "kind": kind,
            "data": f"Samochód: zasięg {km} km, paliwo {litres} l, przebieg {total} km.",
            "question": rng.choice(
                ["Jaki mam zasięg w aucie?", "Ile kilometrów jeszcze przejadę?"]
            ),
            "must": [rf"\b{km}\b"],
            "never": [rf"\b{litres} km"],
        }
    chosen = rng.sample(CHORES, min(4, len(CHORES)))
    who = [rng.choice(people) for _ in chosen]
    pick = rng.randrange(len(chosen))
    lines = ", ".join(f"{c} - {w}" for c, w in zip(chosen, who, strict=True))
    return {
        "kind": "chores",
        "data": f"Obowiązki w tym tygodniu: {lines}.",
        "question": f"Kto w tym tygodniu ma obowiązek „{chosen[pick]}”?",
        "must": [who[pick].lower()[:4]],
        "never": [],
    }


def wiki_question_prompt(titles: list[str]) -> str:
    return knowledge_prompt(titles)


def facts_prompt(question: str, source: str, what: str | None = None) -> str:
    """The judge picks short facts a good answer must have, copied word for word."""
    return FACTS_PROMPT.format(
        question=question, what=what or FACTS_DATA_WORD, source=source, json=_json(FACTS_KEY)
    )


def slot_values_prompt(
    name: str, templates: list[str], household: str, rooms: str, devices: str
) -> str:
    return SLOT_VALUES_PROMPT.format(
        slot="{" + name + "}", templates="; ".join(templates), household=household,
        rooms=rooms, devices=devices, json=_json(VALUES_KEY),
    )  # fmt: skip
