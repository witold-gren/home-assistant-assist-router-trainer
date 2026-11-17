"""Polish: teacher prompts, vocabulary and made-up data for the trainer.

Only data and prompts live here (the integration speaks Polish to the models, so the
training data are Polish too); the logic is in the generators.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import random
from typing import Any

CODE = "pl"
SENTENCES_KEY = "zdania"
QUESTIONS_KEY = "pytania"

# =====================================================================================
# Router: paraphrases written by the teacher
# =====================================================================================

STYLES = [
    "krótkie, potoczne",
    "dłuższe, z kontekstem („bo zaraz wychodzimy”, „jak wrócę”)",
    "z imionami domowników albo „mama”, „tata”, „dzieci”",
    "z błędami jak z rozpoznawania mowy (przekręcone słowa, brak ogonków, „JAkie”)",
    "zaczynające się od „a”, „i”, „no to”, „słuchaj”, „powiedz mi”",
    "pośrednie i nieoczywiste, które człowiek by zrozumiał",
]


def paraphrase_prompt(
    household: str,
    topic: str,
    description: str,
    examples: list[str],
    count: int,
    style: str,
    hint: str,
) -> str:
    shown = "; ".join(examples) if examples else "brak"
    return (
        f"Domownicy: {household} Wygeneruj {count} różnych wypowiedzi po polsku, które domownik "
        f"powiedziałby asystentowi głosowemu na temat: {topic} ({description}). Przykłady: "
        f"{shown}.{hint} Styl: {style}. Każda wypowiedź inna, bez numeracji, bez imienia "
        f'mówiącego na początku. Zwróć JSON: {{"{SENTENCES_KEY}": [...]}}.'
    )


def hint_other(others: str) -> str:
    return (
        " To temat „wszystko inne”: rozmowa, żarty, prośby niezwiązane z domem, pytania, na "
        f"które asystent domu nie ma danych. NIE pisz wypowiedzi pasujących do tematów: {others}."
    )


HINT_KNOWLEDGE = " Pytania o wiedzę ogólną: ludzie, miejsca, historia, nauka, przyroda, definicje."
HINT_UNCLEAR = (
    " To BEŁKOT z błędnego rozpoznania mowy: urwane zdania, przypadkowe słowa, zlepki sylab, "
    "fragmenty rozmów domowników nieskierowane do asystenta, napisy z filmów. Bez sensu "
    "jako polecenie czy pytanie."
)


def hint_control(areas: str, devices: str) -> str:
    return (
        " To POLECENIA sterowania urządzeniami (włącz, wyłącz, ustaw, przyciemnij, rolety, "
        f"temperatura, głośność, muzyka, odkurzacz, lista zakupów). Pokoje: {areas}; "
        f"urządzenia: {devices}."
    )


def hint_rooms(areas: str) -> str:
    return f" Pokoje w domu: {areas}."


def knowledge_prompt(titles: list[str]) -> str:
    """One natural question per encyclopedia title (grammatical forms by the teacher)."""
    listed = "; ".join(titles)
    return (
        "Dla każdego hasła z listy napisz jedno krótkie pytanie po polsku, jakie domownik zadałby "
        "asystentowi głosowemu (np. „Kim był …?”, „Gdzie leży …?”, „Co to jest …?”, „Opowiedz "
        f"mi o …”), z poprawną odmianą. Hasła: {listed}. "
        f'Zwróć JSON: {{"{QUESTIONS_KEY}": [...]}} - po jednym pytaniu na hasło.'
    )


# rendering `command:` templates of router.yaml (reference sentences of a topic):
# (day code, Polish day name) - templates use `when`/`kiedy`
WHEN = [
    (None, None),
    ("today", "dzis"),
    ("tomorrow", "jutro"),
    ("day_after_tomorrow", "pojutrze"),
    ("weekend", "weekend"),
    ("week", "tydzien"),
]
SAMPLE_TEXTS = ["", "kiedy jedzie tramwaj", "czy pralka skończyła", "a dzisiaj?"]

CHAT = [
    "Dziękuję",
    "Dzięki",
    "Co słychać?",
    "Jak się masz?",
    "Kim jesteś?",
    "Opowiedz kawał",
    "Opowiedz jakiś dowcip",
    "Rozśmiesz mnie",
    "Zrób mi kanapkę",
    "Ugotuj obiad",
    "Nudzi mi się",
    "Zaśpiewaj piosenkę",
    "Lubisz mnie?",
    "Cześć",
    "Hej",
    "Halo",
    "Nie, nic",
    "Anuluj",
    "Nieważne",
    "Co potrafisz?",
    "Jak masz na imię?",
    "Powiedz coś miłego",
    "Ile masz lat?",
    "Co u ciebie?",
    "Wymyśl zagadkę",
    "Policz do dziesięciu",
]

# gibberish: pieces of film subtitles and syllable salad (topic with `unclear`)
SUBTITLES = [
    "Dziękuję za oglądanie",
    "Napisy stworzone przez społeczność",
    "Subskrybuj kanał",
    "Do zobaczenia w następnym odcinku",
    "Tłumaczenie i napisy",
    "Zapraszam na kolejny film",
]
SYLLABLES = ["ka", "ro", "mi", "sze", "dla", "prze", "wy", "no", "ta", "ję", "ście", "bu", "ło"]
FILLERS = ["no", "że", "to", "a", "i", "tak", "w", "na", "jak", "bo", "tego", "znaczy", "ten"]

# =====================================================================================
# Control: commands written by the teacher for a planned parse
# =====================================================================================

COMMAND_STYLES = [
    "zwykłe, krótkie polecenia",
    "potoczne, z „proszę”, „możesz”, „zrób”",
    "z błędami jak z rozpoznawania mowy",
    "dłuższe, z powodem („bo ciemno”, „zaraz film”)",
]

FIELD_NAMES = {
    "intent": "intencja",
    "domain": "rodzaj urządzeń",
    "area": "pomieszczenie",
    "floor": "piętro",
    "device": "konkretne urządzenie",
    "all": "wszystkie urządzenia",
    "value": "wartość",
    "change": "zmiana",
    "item": "co dopisać do listy",
    "color": "kolor światła",
    "white": "barwa białego światła",
    "query": "czego szukać",
    "media_class": "rodzaj muzyki",
    "artist": "wykonawca",
    "radio": "podobna muzyka bez końca (radio)",
}


def command_prompt(details: list[str], count: int, style: str) -> str:
    listed = "; ".join(details)
    return (
        f"Napisz {count} różnych poleceń głosowych po polsku dla asystenta domu, które znaczą "
        f"dokładnie to: {listed}. Nie dodawaj innych urządzeń, pomieszczeń ani wartości. Nazwę "
        "urządzenia i pomieszczenia odmieniaj poprawnie (np. „w kuchni”, „lampkę”). Styl: "
        f'{style}. Bez numeracji. Zwróć JSON: {{"{SENTENCES_KEY}": [...]}}.'
    )


MUSIC_WORD = "muzykę"

# =====================================================================================
# Answers: made-up data with facts computed in Python
# =====================================================================================

WEEKDAYS = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
EVENTS = [
    "dentysta",
    "basen",
    "trening piłki",
    "zebranie w szkole",
    "urodziny babci",
    "fryzjer",
    "kino",
    "lekcja gitary",
    "zakupy",
    "wizyta u lekarza",
    "angielski",
    "szachy",
    "przegląd auta",
    "spotkanie z klientem",
    "joga",
    "korepetycje",
    "teatr",
    "tańce",
]
LESSONS = [
    "matematyka",
    "polski",
    "angielski",
    "historia",
    "biologia",
    "geografia",
    "chemia",
    "fizyka",
    "WF",
    "informatyka",
    "plastyka",
    "muzyka",
    "religia",
    "technika",
]
CHORES = ["zmywarka", "odkurzanie", "śmieci", "pranie", "kuchnia", "łazienka", "pies"]
UNKNOWN_QUESTIONS = [
    "Kiedy jest przegląd roweru?",
    "Ile kosztował ostatni rachunek za prąd?",
    "O której przyjedzie kurier?",
    "Kiedy wraca wujek z delegacji?",
    "Jaki jest kod do furtki?",
    "Ile stron przeczytałem wczoraj?",
]
NEGATIVE = r"nie (wiem|mam|ma |widz|znalaz|posiad|mogę)|brak|nic nie"
LESSON_TIMES = [
    ("8:00", "8:45"),
    ("8:55", "9:40"),
    ("9:50", "10:35"),
    ("10:55", "11:40"),
    ("11:50", "12:35"),
    ("12:45", "13:30"),
    ("13:40", "14:25"),
]


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


# =====================================================================================
# Generated test: the test writer (another model than the teacher) and the judge
# =====================================================================================

TEST_STYLE = "naturalne i różnorodne: krótkie i dłuższe, potoczne, czasem niedokładne jak z rozpoznawania mowy"
FACTS_KEY = "fakty"
# stems of words too general to test an answer (patterns of facts.pattern)
FACT_GENERIC = (
    "roku",
    "rok",
    "tys",
    "około",
    "okolo",
    "jest",
    "był",
    "była",
    "było",
    "oraz",
    "który",
    "która",
    "stycz",
    "luteg",
    "marca",
    "kwiet",
    "maja",
    "czerw",
    "lipca",
    "sierp",
    "wrześ",
    "paźdz",
    "listo",
    "grudn",
    "dzien",
    "dzień",
    "godzi",
    "minut",
    "min",
)


def facts_prompt(question: str, source: str, what: str = "danych") -> str:
    """The judge picks short facts a good answer must have, copied word for word."""
    return (
        f"Pytanie: {question}\nPoniżej {what}. Wypisz 2-4 krótkie fakty (godzina, liczba, nazwa, "
        f"jedno-dwa słowa), które MUSI zawierać poprawna odpowiedź na pytanie, a których nie ma "
        f"w samym pytaniu. Wybieraj to, co odpowiedź po polsku powie dosłownie: liczby, godziny, "
        "imiona, polskie nazwy - nie angielskie nazwy atrybutów, marek ani identyfikatory. Każdy fakt skopiuj z {what} ZNAK W ZNAK (te same litery, cyfry i "
        "odmiana), nie tłumacz i nie streszczaj; pomiń angielskie stany urządzeń (np. sunny, on, "
        f"off). Gdy w {what} nie ma odpowiedzi, zwróć pustą listę. "
        f'Zwróć JSON: {{"{FACTS_KEY}": [...]}}.\n\n{source}'
    )


# values of {wildcards} in the sentence triggers of automations
VALUES_KEY = "wartosci"


def slot_values_prompt(
    name: str, templates: list[str], household: str, rooms: str, devices: str
) -> str:
    shown = "; ".join(templates)
    return (
        f"W zdaniach poleceń asystenta domowego jest miejsce {{{name}}}: {shown}. {household} "
        f"Pokoje: {rooms}. Urządzenia (część): {devices}. Podaj 8-12 różnych wartości, które "
        f"domownik naprawdę mógłby powiedzieć w miejscu {{{name}}}, w formie pasującej do zdań "
        f'(odmiana!). Bez numeracji. Zwróć JSON: {{"{VALUES_KEY}": [...]}}.'
    )
