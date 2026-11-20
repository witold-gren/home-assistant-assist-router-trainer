"""Control examples: command -> JSON of the command parser (the integration's keys).

1. Python plans a command from your home snapshot: intent, area, device, value, colour,
   music … (a "label"), e.g. HassLightSet in the kitchen at 40 %.
2. The teacher writes a few natural sentences that mean exactly that (correctly inflected,
   in several styles).
3. The teacher parses every sentence with the integration's own parser prompt and schema; the
   integration's ``parse_command`` and ``find_target`` read the reply. A sentence is kept only
   when the parse matches the plan (and points at the planned device). The kept reply becomes
   the training answer - so the label is checked twice and has the exact runtime format.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from ..context import Context
from ..holdout import Holdout
from ..teacher import PARALLEL
from .common import JsonlWriter, in_parallel, list_schema, progress, sentences_of, stage

# kind -> weight (how often it is planned)
KINDS = {
    "area_on_off": 12,
    "device_on_off": 14,
    "brightness": 7,
    "relative_light": 5,
    "color": 4,
    "white": 3,
    "cover_position": 5,
    "cover_open_close": 6,
    "climate": 4,
    "volume": 4,
    "relative_volume": 3,
    "media": 5,
    "play": 7,
    "vacuum": 3,
    "list": 4,
    "all_off": 3,
    "routine": 6,
}
ON_OFF_DOMAINS = ("light", "switch", "fan", "media_player")


@dataclass
class Label:
    kind: str
    fields: dict[str, Any]  # English keys of the integration's Command
    device: str | None = None  # planned device (find_target must point at it)


def _areas_with(home_data: dict[str, Any], domain: str) -> list[str]:
    return sorted({t["area"] for t in home_data["targets"] if t["domain"] == domain and t["area"]})


def _targets(home_data: dict[str, Any], *domains: str) -> list[dict[str, Any]]:
    return [t for t in home_data["targets"] if t["domain"] in domains]


def plan(ctx: Context, home_data: dict[str, Any], rng: random.Random) -> Label | None:
    """One planned command (None when the home has nothing for the drawn kind)."""
    lang = ctx.integ.lang
    domains = set(home_data["domains"])
    kind = rng.choices(list(KINDS), weights=list(KINDS.values()))[0]
    area_of = {d: _areas_with(home_data, d) for d in ("light", "cover", "climate", "media_player")}
    if kind == "area_on_off" and area_of["light"]:
        intent = rng.choice(["HassTurnOn", "HassTurnOff"])
        return Label(
            kind, {"intent": intent, "domain": "light", "area": rng.choice(area_of["light"])}
        )
    if kind == "device_on_off":
        targets = [t for t in _targets(home_data, *ON_OFF_DOMAINS) if t["domain"] in domains]
        if not targets:
            return None
        target = rng.choice(targets)
        fields = {
            "intent": rng.choice(["HassTurnOn", "HassTurnOff"]),
            "domain": target["domain"],
            "name": rng.choice(target["names"]),
        }
        if target["area"] and rng.random() < 0.4:
            fields["area"] = target["area"]
        return Label(kind, fields, target["name"])
    if kind == "brightness" and area_of["light"]:
        return Label(
            kind,
            {
                "intent": "HassLightSet",
                "domain": "light",
                "area": rng.choice(area_of["light"]),
                "value": rng.randrange(10, 101, 10),
                "change": lang.CHANGE_SET,
            },
        )
    if kind == "relative_light" and area_of["light"]:
        change = rng.choice([lang.CHANGE_MORE, lang.CHANGE_LESS])
        return Label(
            kind,
            {
                "intent": "HassLightSet",
                "domain": "light",
                "area": rng.choice(area_of["light"]),
                "change": change,
            },
        )
    if kind == "color" and area_of["light"]:
        return Label(
            kind,
            {
                "intent": "HassLightSet",
                "domain": "light",
                "area": rng.choice(area_of["light"]),
                "color": rng.choice(list(lang.COLORS)),
            },
        )
    if kind == "white" and area_of["light"]:
        return Label(
            kind,
            {
                "intent": "HassLightSet",
                "domain": "light",
                "area": rng.choice(area_of["light"]),
                "white": rng.choice(list(lang.WHITES)),
            },
        )
    if kind == "cover_position" and area_of["cover"]:
        return Label(
            kind,
            {
                "intent": "HassSetPosition",
                "domain": "cover",
                "area": rng.choice(area_of["cover"]),
                "value": rng.randrange(0, 101, 10),
            },
        )
    if kind == "cover_open_close" and area_of["cover"]:
        return Label(
            kind,
            {
                "intent": rng.choice(["HassTurnOn", "HassTurnOff"]),
                "domain": "cover",
                "area": rng.choice(area_of["cover"]),
            },
        )
    if kind == "climate" and area_of["climate"]:
        return Label(
            kind,
            {
                "intent": "HassClimateSetTemperature",
                "domain": "climate",
                "area": rng.choice(area_of["climate"]),
                "value": rng.randrange(36, 51) / 2,
            },
        )
    if kind == "volume" and area_of["media_player"]:
        return Label(
            kind,
            {
                "intent": "HassSetVolume",
                "domain": "media_player",
                "area": rng.choice(area_of["media_player"]),
                "value": rng.randrange(10, 81, 5),
            },
        )
    if kind == "relative_volume" and area_of["media_player"]:
        change = rng.choice([lang.CHANGE_MORE, lang.CHANGE_LESS])
        return Label(
            kind,
            {
                "intent": "HassSetVolumeRelative",
                "domain": "media_player",
                "area": rng.choice(area_of["media_player"]),
                "change": change,
            },
        )
    if kind == "media" and area_of["media_player"]:
        intent = rng.choice(
            ["HassMediaPause", "HassMediaUnpause", "HassMediaNext", "HassMediaPrevious"]
        )
        return Label(
            kind,
            {
                "intent": intent,
                "domain": "media_player",
                "area": rng.choice(area_of["media_player"]),
            },
        )
    if kind == "play" and area_of["media_player"]:
        music = ctx.settings["music"]
        roll = rng.random()
        if roll < 0.5:
            fields = {"query": rng.choice(music["artists"]), "media_class": _media(lang, "artist")}
            if rng.random() < 0.3:
                fields["radio"] = True
        elif roll < 0.8:
            fields = {"query": rng.choice(music["genres"]), "media_class": _media(lang, "genre")}
        else:
            fields = {
                "query": rng.choice(music["playlists"]),
                "media_class": _media(lang, "playlist"),
            }
        return Label(
            kind,
            {
                "intent": "HassMediaSearchAndPlay",
                "domain": "media_player",
                "area": rng.choice(area_of["media_player"]),
                **fields,
            },
        )
    if kind == "vacuum" and "vacuum" in domains:
        intent = rng.choice(["HassVacuumStart", "HassVacuumReturnToBase"])
        return Label(kind, {"intent": intent, "domain": "vacuum"})
    if kind == "list" and "todo" in domains:
        return Label(
            kind,
            {
                "intent": "HassListAddItem",
                "domain": "todo",
                "item": rng.choice(ctx.settings["shopping_items"]),
            },
        )
    if kind == "all_off" and "light" in domains:
        return Label(
            kind,
            {"intent": rng.choice(["HassTurnOff", "HassTurnOn"]), "domain": "light", "all": True},
        )
    if kind == "routine" and home_data.get("actions"):
        name = rng.choice(sorted(home_data["actions"]))
        target = next((t for t in home_data["targets"] if t["name"] == name), None)
        domain = target["domain"] if target else "script"
        return Label(kind, {"intent": "HassTurnOn", "domain": domain, "name": name}, name)
    return None


def _media(lang: Any, english: str) -> str | None:
    """Language pack name of a media class (e.g. „wykonawca” for artist)."""
    return next((name for name, value in lang.MEDIA_CLASSES.items() if value == english), None)


def details(ctx: Context, label: Label) -> list[str]:
    """The plan in words for the teacher („intencja: …; pomieszczenie: Kuchnia; …”)."""
    lang, names = ctx.integ.lang, ctx.pack.FIELD_NAMES
    out = []
    for key, value in label.fields.items():
        if value is None or value is False:
            continue
        if key == "intent":
            out.append(f"{names['intent']}: {lang.INTENTS[value][0]}")
        elif key == "domain":
            out.append(f"{names['domain']}: {lang.DOMAINS.get(value, value)}")
        elif key == "name":
            out.append(f"{names['device']}: „{value}”")
        elif value is True:
            out.append(names[key])
        else:
            out.append(f"{names[key]}: {spoken_number(value)}")
    return out


def spoken_number(value: Any) -> Any:
    """22.0 -> 22, 22.5 -> „22,5” - as people say it, not as Python prints it."""
    if isinstance(value, float):
        return int(value) if value.is_integer() else str(value).replace(".", ",")
    return value


def _text_ok(expected: str, got: Any) -> bool:
    return isinstance(got, str) and expected.lower() in got.lower()


def matches(label: Label, command: Any, device: str | None, set_word: str | None = None) -> bool:
    """Does the parsed command say what was planned?

    ``set_word`` - the language's "set" change („ustaw”): a value set outright, the same as no
    change. A planned device that was found counts even under another domain (a switch and a
    script of the same name)."""
    if command is None:
        return False
    fields = label.fields
    if command.intent != fields["intent"]:
        return False
    found_planned = bool(label.device) and device == label.device
    if fields.get("domain") and command.domain != fields["domain"] and not found_planned:
        return False
    # a device command without a planned room may name the room (it is part of many names)
    if ("area" in fields or label.device is None) and command.area != fields.get("area"):
        return False
    change = None if command.change == set_word else command.change
    if change != (None if fields.get("change") == set_word else fields.get("change")):
        return False
    for key in ("color", "white", "media_class"):
        if getattr(command, key) != fields.get(key):
            return False
    if bool(command.all) != bool(fields.get("all")) or bool(command.radio) != bool(
        fields.get("radio")
    ):
        return False
    if "value" in fields and (
        command.value is None or abs(float(command.value) - float(fields["value"])) > 0.01
    ):
        return False
    for key in ("query", "item"):
        if key in fields and not _text_ok(fields[key], getattr(command, key)):
            return False
    return not (label.device and device != label.device)


def answer_fields(command: Any) -> dict[str, Any]:
    """Fields of the training answer from the accepted parse (whole numbers without .0)."""
    value = command.value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return {
        "intent": command.intent,
        "domain": command.domain,
        "area": command.area,
        "floor": command.floor,
        "name": command.name,
        "all": command.all,
        "value": value,
        "change": command.change,
        "item": command.item,
        "color": command.color,
        "white": command.white,
        "query": command.query,
        "media_class": command.media_class,
        "artist": command.artist,
        "radio": command.radio,
    }


# labels per round: their sentences are written side by side, then all of them are read back
# side by side - the long control prompt stays in the teacher's cache for the whole round
BATCH = 24


def plans(ctx: Context, home_data: dict[str, Any]) -> list[tuple[int, Label, str, int]]:
    """Every planned command: (index, plan, style, seed) - the same on every run (the handoff
    of a manual writer exports exactly these)."""
    rng = ctx.rng("control")
    out = []
    for index in range(ctx.settings["generate"]["control"]["labels"]):
        label = None
        while label is None:
            label = plan(ctx, home_data, rng)
        style = ctx.pack.COMMAND_STYLES[index % len(ctx.pack.COMMAND_STYLES)]
        out.append((index, label, style, rng.randrange(1 << 30)))
    return out


def external_sentences(ctx: Context) -> dict[int, list[str]]:
    """Sentences a manual writer wrote for the plans (router-trainer handoff import writer)."""
    from .common import read_jsonl

    out: dict[int, list[str]] = {}
    for row in read_jsonl(ctx.ws.generated / "handoff" / "control-external.jsonl"):
        out.setdefault(int(row["label"]), []).append(row["text"])
    return out


def generate(ctx: Context) -> Any:
    """Write workspace/generated/control.jsonl (resumable)."""
    from ..teacher import is_manual

    if is_manual(ctx.settings, "judge"):
        raise RuntimeError(
            "control: parsing the commands back needs a model judge (teacher.judge: ollama, "
            "openai or claude) - by hand it would be the label itself"
        )
    manual_writer = is_manual(ctx.settings, "writer")
    external = external_sentences(ctx) if manual_writer else {}
    stage("control")
    settings = ctx.settings["generate"]["control"]
    holdout: Holdout = ctx.holdout()
    home_data = ctx.home_data()
    household = ctx.config.household
    system_messages = ctx.integ.control_messages(home_data, household, "")[:1]
    schema = ctx.integ.control_schema(home_data)
    key = ctx.pack.SENTENCES_KEY
    teacher, judge = ctx.teacher("writer"), ctx.teacher("judge")
    out = ctx.ws.generated / "control.jsonl"
    target = settings["labels"] * settings["sentences_per_label"]
    counts = {"rejected": 0, "holdout": 0}

    def write(job: tuple[int, Label, str, int]) -> list[str]:
        index, label, style, seed = job
        if manual_writer:
            return external.get(index, [])
        prompt = ctx.pack.command_prompt(
            details(ctx, label), settings["sentences_per_label"], style
        )
        reply = teacher.json(
            [{"role": "user", "content": prompt}],
            list_schema(key),
            temperature=0.9,
            num_predict=600,
            seed=seed,
        )
        return sentences_of(reply, key)

    def read(text: str) -> tuple[Any, list[dict[str, str]]]:
        messages = [*system_messages, ctx.integ.control_messages(home_data, household, text)[1]]
        return judge.json(messages, schema, num_predict=160), messages

    with JsonlWriter(out) as writer:
        done_labels = {row.get("label") for row in _rows(out)}
        # the same plans on a resumed run; a manual writer's plans wait for their sentences
        jobs = [
            job
            for job in plans(ctx, home_data)
            if job[0] not in done_labels and (not manual_writer or job[0] in external)
        ]
        for first in range(0, len(jobs), BATCH):
            batch = jobs[first : first + BATCH]
            written = in_parallel(write, batch, PARALLEL)
            pairs = []
            for job, texts in zip(batch, written, strict=True):
                for text in texts:
                    if holdout.match(text):
                        counts["holdout"] += 1
                    else:
                        pairs.append((job, text))
            readings = in_parallel(lambda pair: read(pair[1]), pairs, PARALLEL)
            for (job, text), (parsed, messages) in zip(pairs, readings, strict=True):
                _keep(ctx, writer, home_data, job[0], job[1], text, parsed, messages, counts)
            progress("control", "control", len(writer.seen), target, sum(counts.values()))
    print(
        f"control: rejected by the check {counts['rejected']}, like a test command "
        f"{counts['holdout']}",
        flush=True,
    )
    return out


def _keep(
    ctx: Context,
    writer: JsonlWriter,
    home_data: dict[str, Any],
    index: int,
    label: Label,
    text: str,
    parsed: Any,
    messages: list[dict[str, str]],
    counts: dict[str, int],
) -> None:
    """A sentence the teacher read back: kept when it says what was planned."""
    command = ctx.integ.parse_command(home_data, _dumps(parsed))
    match = ctx.integ.find_target(home_data, command, messages[1]["content"]) if command else None
    device = match.target.name if match and match.target else None
    if not matches(label, command, device, ctx.integ.lang.CHANGE_SET):
        counts["rejected"] += 1
        # for review: what was planned and how the teacher read the sentence
        log_rejected(
            ctx.ws.generated / "control_rejected.jsonl",
            {
                "kind": label.kind,
                "plan": label.fields,
                "device": label.device,
                "text": text,
                "parsed": answer_fields(command) if command else None,
                "found": device,
            },
        )
        return
    writer.write(
        {
            "role": "control",
            "part": f"control:{label.kind}",
            "label": index,
            "text": text,
            "answer": ctx.integ.control_answer(home_data, answer_fields(command)),
            "source": "teacher",
        }
    )


def log_rejected(path: Any, row: dict[str, Any]) -> None:
    import json

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False) if value is not None else ""


def _rows(path: Any) -> list[dict[str, Any]]:
    from .common import read_jsonl

    return list(read_jsonl(path))
