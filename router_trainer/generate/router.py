"""Router examples: question -> topic of router.yaml.

Sources (each row keeps its source, so the dataset card shows the mix):
- ``trigger``: sentence triggers of your automations (hassil templates); the topic comes from
  the topic's reference sentence (``command`` in router.yaml) or ``topic_overrides``;
- ``intent``: built-in HA intents (home-assistant-intents) with your entity, area and floor
  names - commands go to the control topic, weather etc. by ``intent_topics``;
- ``custom``: your own ``custom_sentences`` of Home Assistant, the same way (an intent of your
  own ``intent_script`` gets the topic the teacher picks, or ``topic_overrides`` ``intent:<name>``);
- ``paraphrase``: natural questions the teacher writes per topic, in several styles;
- ``knowledge``: questions about random encyclopedia titles (topic with ``search``);
- ``chat`` and ``gibberish``: small talk and speech recognition noise (fallback / unclear topic);
- ``log``: real questions from unrecognized_commands.csv that are unlike every test question,
  labelled by the teacher with the integration's own router prompt;
- ``recording`` and ``asr``: the home's own voice commands and natural questions read aloud,
  both written by the home's Whisper (``speech.py``).

Test sentences are dropped on the way (exact and near duplicates).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import csv
import json
from pathlib import Path
import random
import re
from typing import Any
import urllib.parse
import urllib.request

import yaml

from ..context import Context
from ..holdout import Holdout, normalize
from ..teacher import is_manual
from .common import JsonlWriter, list_schema, progress, sample, sentences_of, stage

PARAPHRASE_BATCH = 25
KNOWLEDGE_BATCH = 20
USER_AGENT = "home-assistant-assist-router-trainer (training data)"


# --- sentence triggers of automations ------------------------------------------------------------


class _HaLoader(yaml.SafeLoader):
    """YAML of the HA config: !secret, !include … are read as None."""


_HaLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def load_ha_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_HaLoader)


def conversation_triggers(config_dir: Path) -> list[dict[str, Any]]:
    """[{key, id, alias, templates}] - one per `conversation` trigger."""
    files = [config_dir / "automations.yaml", *sorted((config_dir / "packages").glob("*.yaml"))]
    found = []
    for file in files:
        if not file.exists() or "backup" in file.name or ".bak" in file.name:
            continue
        data = load_ha_yaml(file.read_text(encoding="utf-8"))
        automations = data if isinstance(data, list) else (data or {}).get("automation") or []
        if isinstance(automations, dict):
            automations = list(automations.values())
        for automation in automations if isinstance(automations, list) else []:
            if not isinstance(automation, dict):
                continue
            triggers = automation.get("triggers") or automation.get("trigger") or []
            triggers = triggers if isinstance(triggers, list) else [triggers]
            number = 0
            for trigger in triggers:
                if not isinstance(trigger, dict):
                    continue
                if (trigger.get("trigger") or trigger.get("platform")) != "conversation":
                    continue
                commands = trigger.get("command")
                commands = commands if isinstance(commands, list) else [commands]
                found.append(
                    {
                        "key": f"{automation.get('id')}#{number}",
                        "id": str(automation.get("id")),
                        "alias": str(automation.get("alias", "")),
                        "templates": [str(c) for c in commands if c],
                    }
                )
                number += 1
    return found


def _regex(function):
    """A regular-expression filter or test of HA templates (``ignorecase`` keyword)."""

    def call(value: Any, pattern: str = "", ignorecase: bool = False) -> Any:
        return function(pattern, str(value), re.IGNORECASE if ignorecase else 0)

    return call


def canonical_commands(ctx: Context) -> dict[str, set[str]]:
    """Reference sentences of every topic with a `command` template (many variable sets)."""
    import jinja2

    env = jinja2.Environment()
    # the regular-expression filters and tests of HA templates
    env.filters["regex_findall"] = _regex(re.findall)
    env.tests["search"] = _regex(lambda *a: re.search(*a) is not None)
    env.tests["match"] = _regex(lambda *a: re.match(*a) is not None)
    route_class = ctx.integ.router.Route
    out: dict[str, set[str]] = defaultdict(set)
    for topic in ctx.config.topics.values():
        if not topic.command:
            continue
        try:
            template = env.from_string(topic.command)
        except jinja2.TemplateError as err:
            print(f"  ! command of {topic.name} skipped: {err}", flush=True)
            continue
        for person in [None, *ctx.config.people]:
            for when, _ in ctx.pack.WHEN:
                for text in ctx.pack.SAMPLE_TEXTS:
                    route = route_class(topic.name, person, when, None, (person,) if person else ())
                    variables = ctx.integ.router.template_variables(ctx.config, route, text)
                    try:
                        command = " ".join(template.render(**variables).split())
                    except jinja2.TemplateError:
                        continue
                    if command:
                        out[topic.name].add(command)
    return out


def map_triggers(
    triggers: list[dict[str, Any]],
    commands: dict[str, set[str]],
    overrides: dict[str, str],
    language: str = "pl",
) -> dict[str, str]:
    """Trigger key -> topic: matches a reference sentence, or an override from trainer.yaml."""
    from hassil import Intents, recognize
    from hassil.intents import WildcardSlotList

    mapping = {}
    for trigger in triggers:
        override = overrides.get(trigger["key"]) or overrides.get(trigger["id"])
        if override:
            mapping[trigger["key"]] = override
            continue
        slots = {
            name: WildcardSlotList(name)
            for template in trigger["templates"]
            for name in re.findall(r"\{(\w+)\}", template)
        }
        try:
            intents = Intents.from_dict(
                {
                    "language": language,
                    "intents": {"t": {"data": [{"sentences": trigger["templates"]}]}},
                }
            )
        except Exception as err:
            print(f"  ! skipped {trigger['key']}: {err}", flush=True)
            continue
        for topic, sentences in commands.items():
            if any(recognize(s, intents, slot_lists=slots) for s in sentences):
                mapping[trigger["key"]] = topic
                break
    return mapping


class Expander:
    """A random sentence from a hassil template (all combinations can be millions)."""

    def __init__(self, lists: dict[str, Any], rules: dict[str, Any], rng: random.Random) -> None:
        self.lists, self.rules, self.rng = lists, rules, rng

    def text(self, expression: Any) -> str:
        return " ".join(self._expand(expression).split())

    def _expand(self, e: Any) -> str:
        from hassil.expression import (
            Alternative,
            Group,
            ListReference,
            Permutation,
            RuleReference,
            Sentence,
            Sequence,
            TextChunk,
        )

        if isinstance(e, Sentence):
            return self._expand(e.expression)
        if isinstance(e, TextChunk):
            return e.text
        if isinstance(e, Alternative):
            return self._expand(self.rng.choice(e.items))
        if isinstance(e, Permutation):
            items = list(e.items)
            self.rng.shuffle(items)
            return " ".join(self._expand(i) for i in items)
        if isinstance(e, (Sequence, Group)):
            return "".join(self._expand(i) for i in e.items)
        if isinstance(e, ListReference):
            return self._list_value(e.list_name)
        if isinstance(e, RuleReference):
            rule = self.rules.get(e.rule_name)
            return self._expand(rule) if rule is not None else ""
        raise ValueError(f"unknown expression: {type(e).__name__}")

    def _list_value(self, name: str) -> str:
        from hassil.intents import RangeSlotList, TextSlotList

        slot_list = self.lists.get(name)
        if isinstance(slot_list, TextSlotList) and slot_list.values:
            return self._expand(self.rng.choice(slot_list.values).text_in)
        if isinstance(slot_list, RangeSlotList):
            step = slot_list.step or 1
            return str(self.rng.randrange(slot_list.start, slot_list.stop + 1, step))
        if isinstance(slot_list, list) and slot_list:  # own values for {wildcards}
            return str(self.rng.choice(slot_list))
        return ""


def home_names(home_data: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """(device names with aliases, area names with aliases, floor names with aliases)."""
    devices = sorted({n for t in home_data["targets"] for n in t["names"] if n})
    return devices, sorted(home_data["areas"]), sorted(home_data["floors"])


def trigger_sentences(
    ctx: Context,
    home_data: dict[str, Any],
    rng: random.Random,
    classify: Callable[[list[str]], str | None] | None = None,
    propose: Callable[[str, list[str]], list[str]] | None = None,
    skip_unknown: bool = False,
) -> list[tuple]:
    """Sentences of every trigger with its topic. A trigger without a matching reference
    sentence or override gets the topic ``classify`` picks for a few of its sentences (the
    teacher), else ``fallback_topic``; the choices are saved to generated/trigger_topics.json
    for review (fix one with ``topic_overrides``). A ``{wildcard}`` without values in
    ``slot_values`` gets the values ``propose`` suggests (the teacher, from the templates, the
    household, rooms and devices), saved to generated/slot_values.json for review; without
    ``propose``: room and device names."""
    from hassil import parse_sentence

    triggers = conversation_triggers(ctx.input("ha_config"))
    mapping = map_triggers(
        triggers,
        canonical_commands(ctx),
        ctx.settings.get("topic_overrides") or {},
        ctx.integ.lang.CODE,
    )
    fallback = ctx.settings["fallback_topic"]
    devices, areas, _ = home_names(home_data)
    default_values = areas + devices[:200]
    slot_values = auto_slot_values(ctx, triggers, propose)
    cache_file = ctx.ws.generated / "trigger_topics.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    out = []
    for trigger in triggers:
        lists = {
            name: slot_values.get(name, default_values)
            for template in trigger["templates"]
            for name in re.findall(r"\{(\w+)\}", template)
        }
        expander = Expander(lists, {}, rng)
        texts = []
        for template in trigger["templates"]:
            try:
                sentence = parse_sentence(template)
            except Exception:  # templates hassil cannot read are skipped
                continue
            texts += [
                expander.text(sentence)
                for _ in range(ctx.settings["generate"]["router"]["per_template"])
            ]
        texts = [t for t in dict.fromkeys(texts) if t]
        topic, how = mapping.get(trigger["key"]), "reference"
        if topic is None and trigger["key"] in cache:
            topic, how = cache[trigger["key"]]["topic"], "teacher"
        elif topic is None and classify is not None and texts:
            topic, how = classify(texts[:5]), "teacher"
            cache[trigger["key"]] = {"alias": trigger["alias"], "topic": topic, "sample": texts[:3]}
        if topic is None and skip_unknown:  # judged by hand: no guessing - set topic_overrides
            print(f"  {'-':20} skipped   {trigger['key']:36} {trigger['alias'][:50]} "
                  "(no topic: topic_overrides)", flush=True)  # fmt: skip
            continue
        if topic is None:
            topic, how = fallback, "fallback"
        print(f"  {topic:20} {how:9} {trigger['key']:36} {trigger['alias'][:50]}", flush=True)
        if topic not in ctx.config.topics:
            print(f"  ! topic {topic} not in router.yaml - {trigger['key']} skipped", flush=True)
            continue
        out += [(text, topic, "trigger") for text in texts]
    if cache:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sentence triggers: {len(triggers)}, by reference sentence or override: {len(mapping)}")
    return out


def trigger_report(ctx: Context) -> list[dict[str, Any]]:
    """Every sentence trigger with the topic its sentences get and how (``override`` of
    trainer.yaml, ``reference`` sentence of router.yaml, the ``teacher``'s earlier choice, or
    ``none`` yet) - the list to write ``topic_overrides`` from for a new home."""
    triggers = conversation_triggers(ctx.input("ha_config"))
    overrides = ctx.settings.get("topic_overrides") or {}
    mapping = map_triggers(triggers, canonical_commands(ctx), {}, ctx.integ.lang.CODE)
    cache_file = ctx.ws.generated / "trigger_topics.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    out = []
    for trigger in triggers:
        override = overrides.get(trigger["key"]) or overrides.get(trigger["id"])
        if override:
            topic, how = override, "override"
        elif trigger["key"] in mapping:
            topic, how = mapping[trigger["key"]], "reference"
        elif trigger["key"] in cache:
            topic, how = cache[trigger["key"]]["topic"], "teacher"
        else:
            topic, how = None, "none"
        out.append(
            {
                "key": trigger["key"],
                "alias": trigger["alias"],
                "topic": topic,
                "how": how,
                "known_topic": topic in ctx.config.topics,
                "templates": trigger["templates"][:3],
            }
        )
    return out


def auto_slot_values(
    ctx: Context,
    triggers: list[dict[str, Any]],
    propose: Callable[[str, list[str]], list[str]] | None,
) -> dict[str, list[str]]:
    """Values of every ``{wildcard}``: trainer.yaml first, then the saved suggestions, then new
    suggestions (saved to generated/slot_values.json)."""
    own = dict(ctx.settings.get("slot_values") or {})
    cache_file = ctx.ws.generated / "slot_values.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    templates: dict[str, list[str]] = defaultdict(list)
    for trigger in triggers:
        for template in trigger["templates"]:
            for name in re.findall(r"\{(\w+)\}", template):
                templates[name].append(template)
    changed = False
    for name, used in templates.items():
        if name in own:
            continue
        if name not in cache and propose is not None:
            values = [v for v in propose(name, sorted(set(used))[:6]) if v]
            if values:
                cache[name] = values
                changed = True
        if name in cache:
            own[name] = cache[name]
    if changed:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return own


def teacher_slot_values(ctx: Context, home_data: dict[str, Any]) -> Callable:
    """The teacher's values for one wildcard of your sentence triggers."""
    teacher = ctx.teacher("writer")
    key = ctx.pack.VALUES_KEY
    devices, _, _ = home_names(home_data)
    rooms = ", ".join(sorted(set(home_data["areas"].values())))

    def propose(name: str, templates: list[str]) -> list[str]:
        prompt = ctx.pack.slot_values_prompt(
            name, templates, ctx.config.household, rooms, ", ".join(devices[:40])
        )
        reply = teacher.json(
            [{"role": "user", "content": prompt}], list_schema(key), num_predict=400
        )
        return sentences_of(reply, key)[:12]

    return propose


def teacher_classifier(ctx: Context) -> Callable[[list[str]], str | None]:
    """The teacher's topic for a few sentences of one trigger (majority of its answers)."""
    teacher = ctx.teacher("judge")
    schema = ctx.integ.router_schema(ctx.config)

    def classify(texts: list[str]) -> str | None:
        votes: dict[str, int] = defaultdict(int)
        for text in texts:
            reply = teacher.json(
                ctx.integ.router_messages(ctx.config, text), schema, num_predict=30
            )
            topic = (reply or {}).get(ctx.integ.lang.TOPIC_KEY)
            if topic in ctx.config.topics:
                votes[topic] += 1
        return max(votes, key=votes.get) if votes else None

    return classify


# --- built-in HA intents ------------------------------------------------------------------------


def native_sentences(ctx: Context, home_data: dict[str, Any], rng: random.Random) -> list[tuple]:
    from hassil import Intents, parse_sentence
    from hassil.intents import TextSlotList
    import home_assistant_intents

    count = ctx.settings["generate"]["router"]["native_intents"]
    control_topic = next((t.name for t in ctx.config.topics.values() if t.control), None)
    intent_topics = ctx.settings.get("intent_topics") or {}
    fallback = ctx.settings["fallback_topic"]
    commands = set(ctx.integ.lang.INTENTS)
    intents = Intents.from_dict(home_assistant_intents.get_intents(ctx.integ.lang.CODE))
    lists = dict(intents.slot_lists)
    devices, areas, floors = home_names(home_data)
    for name, values in (("name", devices), ("area", areas), ("floor", floors)):
        if values:
            lists[name] = TextSlotList.from_strings(values)
    expander = Expander(lists, intents.expansion_rules, rng)
    sentences = [
        (intent.name, parse_sentence(s) if isinstance(s, str) else s)
        for intent in intents.intents.values()
        for data in intent.data
        for s in data.sentences
    ]
    out = []
    for _ in range(count):
        intent_name, sentence = rng.choice(sentences)
        text = expander.text(sentence)
        if not text:
            continue
        if intent_name in intent_topics:
            topic = intent_topics[intent_name]
        elif intent_name in commands and control_topic:
            topic = control_topic
        else:
            topic = fallback
        if topic in ctx.config.topics:
            out.append((text, topic, "intent"))
    return out


# --- gibberish and chat -----------------------------------------------------------------------


def custom_sentences(
    ctx: Context,
    home_data: dict[str, Any],
    rng: random.Random,
    classify: Callable[[list[str]], str | None] | None = None,
) -> list[tuple]:
    """Sentences of Home Assistant's own ``custom_sentences/<language>/*.yaml`` (fetched with the
    export). An intent of HA's command list goes to the control topic; one in ``intent_topics``
    or ``topic_overrides`` (``intent:<name>``) to that topic; any other (an ``intent_script`` of
    the home) gets the topic the teacher picks for a few of its sentences, saved with the
    trigger topics (generated/trigger_topics.json) for review."""
    from hassil import Intents, parse_sentence
    from hassil.intents import TextSlotList, WildcardSlotList

    folder = ctx.input("ha_config") / "custom_sentences" / ctx.integ.lang.CODE
    files = sorted(folder.glob("*.yaml")) if folder.is_dir() else []
    if not files:
        return []
    data: dict[str, Any] = {"language": ctx.integ.lang.CODE, "intents": {}}
    for file in files:
        try:
            Intents.from_dict(load_ha_yaml(file.read_text(encoding="utf-8")) or {})
        except Exception as err:  # a file hassil cannot read is skipped, the others stay
            print(f"  ! custom sentences {file.name} skipped: {err}", flush=True)
            continue
        part = load_ha_yaml(file.read_text(encoding="utf-8")) or {}
        for name, intent in (part.get("intents") or {}).items():
            data["intents"].setdefault(name, {"data": []})["data"] += intent.get("data") or []
        for key in ("lists", "expansion_rules"):
            data.setdefault(key, {}).update(part.get(key) or {})
    intents = Intents.from_dict(data)
    devices, areas, floors = home_names(home_data)
    lists: dict[str, Any] = {}
    for name, slot_list in intents.slot_lists.items():
        own = (ctx.settings.get("slot_values") or {}).get(name)
        if own:
            lists[name] = list(own)
        elif isinstance(slot_list, WildcardSlotList):
            lists[name] = areas + devices[:200]
        else:
            lists[name] = slot_list
    for name, values in (("name", devices), ("area", areas), ("floor", floors)):
        if values and name not in lists:
            lists[name] = TextSlotList.from_strings(values)
    expander = Expander(lists, intents.expansion_rules, rng)
    per_template = ctx.settings["generate"]["router"]["per_template"]
    control_topic = next((t.name for t in ctx.config.topics.values() if t.control), None)
    intent_topics = ctx.settings.get("intent_topics") or {}
    overrides = ctx.settings.get("topic_overrides") or {}
    cache_file = ctx.ws.generated / "trigger_topics.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    out = []
    for name, intent in intents.intents.items():
        texts = []
        for block in intent.data:
            for template in block.sentences:
                sentence = parse_sentence(template) if isinstance(template, str) else template
                texts += [expander.text(sentence) for _ in range(per_template)]
        texts = [t for t in dict.fromkeys(texts) if t]
        key = f"intent:{name}"
        topic = overrides.get(key) or intent_topics.get(name)
        if topic is None and name in ctx.integ.lang.INTENTS:
            topic = control_topic
        if topic is None and key in cache:
            topic = cache[key]["topic"]
        elif topic is None and classify is not None and texts:
            topic = classify(texts[:5])
            cache[key] = {"alias": name, "topic": topic, "sample": texts[:3]}
        topic = topic or ctx.settings["fallback_topic"]
        print(f"  {topic:20} custom    {name}", flush=True)
        if topic in ctx.config.topics:
            out += [(text, topic, "custom") for text in texts]
    if cache:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def gibberish(ctx: Context, rng: random.Random, count: int) -> list[str]:
    pack = ctx.pack
    out = []
    for _ in range(count):
        roll = rng.random()
        if roll < 0.3:
            text = rng.choice(pack.SUBTITLES)
        elif roll < 0.65:
            words = [
                "".join(rng.choice(pack.SYLLABLES) for _ in range(rng.randrange(1, 4)))
                for _ in range(rng.randrange(2, 6))
            ]
            text = " ".join(words)
        else:
            words = rng.choices(pack.FILLERS, k=rng.randrange(3, 8))
            text = " ".join(words)
        out.append(text[0].upper() + text[1:] if text else text)
    return out


# --- teacher: paraphrases, knowledge questions, log labels -------------------------------------


def topic_hint(ctx: Context, topic: Any, home_data: dict[str, Any], rng: random.Random) -> str:
    pack = ctx.pack
    devices, _, _ = home_names(home_data)
    rooms = ", ".join(sample(sorted(set(home_data["areas"].values())), 6, rng))
    if topic.name == ctx.settings["fallback_topic"]:
        others = ", ".join(t for t in ctx.config.topics if t != topic.name)
        return pack.hint_other(others)
    if topic.search:
        return pack.HINT_KNOWLEDGE
    if topic.unclear:
        return pack.HINT_UNCLEAR
    if topic.control:
        return pack.hint_control(rooms, ", ".join(sample(devices, 8, rng)))
    return pack.hint_rooms(rooms)


def paraphrases(
    ctx: Context,
    writer: JsonlWriter,
    holdout: Holdout,
    home_data: dict[str, Any],
    checker: Any = None,
) -> None:
    """Teacher sentences per topic; with a ``checker`` (labels.Checker) only the ones the
    teacher, asked with the router's own prompt, puts in the same topic."""
    settings = ctx.settings["generate"]["router"]
    target = settings["paraphrases_per_topic"]
    rng = ctx.rng("paraphrase")
    teacher = ctx.teacher("writer")
    key = ctx.pack.SENTENCES_KEY
    schema = list_schema(key)
    for topic in ctx.config.topics.values():
        part = f"paraphrase:{topic.name}"
        tries, rejected = 0, 0
        while writer.count(part) < target and tries < max(3, -(-target // PARAPHRASE_BATCH) * 3):
            tries += 1
            style = ctx.pack.STYLES[tries % len(ctx.pack.STYLES)]
            prompt = ctx.pack.paraphrase_prompt(
                ctx.config.household,
                topic.name,
                topic.description,
                list(topic.examples),
                PARAPHRASE_BATCH,
                style,
                topic_hint(ctx, topic, home_data, rng),
            )
            reply = teacher.json(
                [{"role": "user", "content": prompt}],
                schema,
                temperature=1.0,
                num_predict=1500,
                seed=rng.randrange(1 << 30),
            )
            texts = [t for t in sentences_of(reply, key) if (part, normalize(t)) not in writer.seen]
            if checker is not None:
                checker.ask([t for t in texts if not holdout.match(t)])
            for text in texts:
                if holdout.match(text) or (checker and not checker.agrees(text, topic.name)):
                    rejected += 1
                    continue
                writer.write(
                    {
                        "role": "router",
                        "part": part,
                        "text": text,
                        "topic": topic.name,
                        "source": "paraphrase",
                    }
                )
            progress("router", part, writer.count(part), target, rejected)


def wikipedia_titles(cache: Path, count: int, exclude: set[str], language: str = "pl") -> list[str]:
    """Random titles of the Wikipedia of ``language`` (cached); test phrases are left out."""
    titles: list[str] = json.loads(cache.read_text()) if cache.exists() else []
    while len(titles) < count:
        params = {
            "action": "query",
            "format": "json",
            "list": "random",
            "rnnamespace": "0",
            "rnlimit": "500",
        }
        request = urllib.request.Request(
            f"https://{language}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params),
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            for page in json.load(response)["query"]["random"]:
                title = re.sub(r"\s*\(.*\)$", "", page["title"])
                if 2 < len(title) <= 40 and ":" not in title and not title[0].isdigit():
                    titles.append(title)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(titles, ensure_ascii=False))
    return [t for t in titles if normalize(t) not in exclude]


def knowledge(ctx: Context, writer: JsonlWriter, holdout: Holdout, titles: list[str]) -> None:
    topic = next((t.name for t in ctx.config.topics.values() if t.search), None)
    if topic is None:
        return
    target = ctx.settings["generate"]["router"]["knowledge"]
    part = "knowledge"
    teacher = ctx.teacher("writer")
    key = ctx.pack.QUESTIONS_KEY
    rejected = 0
    for start in range(0, len(titles), KNOWLEDGE_BATCH):
        if writer.count(part) >= target:
            break
        batch = titles[start : start + KNOWLEDGE_BATCH]
        reply = teacher.json(
            [{"role": "user", "content": ctx.pack.knowledge_prompt(batch)}],
            list_schema(key),
            temperature=0.7,
            num_predict=1500,
        )
        for text in sentences_of(reply, key):
            if holdout.match(text):
                rejected += 1
                continue
            writer.write(
                {
                    "role": "router",
                    "part": part,
                    "text": text,
                    "topic": topic,
                    "source": "knowledge",
                }
            )
        progress("router", part, writer.count(part), target, rejected)


def log_texts(path: Path) -> list[str]:
    """Distinct questions of unrecognized_commands.csv (column `text`)."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    return list(dict.fromkeys(r["text"].strip() for r in rows if (r.get("text") or "").strip()))


def log_questions(ctx: Context, writer: JsonlWriter, holdout: Holdout) -> None:
    """Real questions unlike the test, topic from the teacher with the router prompt."""
    texts = log_texts(ctx.input("log"))
    kept, rejected = holdout.split(texts)
    part = "log"
    print(f"log: {len(texts)} distinct questions, {len(rejected)} like a test question", flush=True)
    from .labels import Checker

    checker = Checker(ctx)  # the judge's topics, kept in generated/labels.json
    todo = [text for text in kept if (part, normalize(text)) not in writer.seen]
    checker.ask(todo)
    for text in todo:
        topic = checker.topic(text)
        if topic in ctx.config.topics:
            writer.write(
                {"role": "router", "part": part, "text": text, "topic": topic, "source": "log"}
            )
    progress("router", part, writer.count(part), len(kept), len(rejected))


def generate(ctx: Context) -> Path:
    """Write workspace/generated/router.jsonl (resumable)."""
    stage("router")
    settings = ctx.settings["generate"]["router"]
    holdout = ctx.holdout()
    home_data = ctx.home_data()
    out = ctx.ws.generated / "router.jsonl"
    from . import labels

    checker = labels.Checker(ctx) if labels.checked_sources(ctx) else None
    if checker is not None:  # teacher sentences router.yaml puts elsewhere go (refilled below)
        labels.clean(ctx, checker)
    with JsonlWriter(out) as writer:
        rng = ctx.rng("templates")
        fixed: list[tuple] = []
        manual_writer = is_manual(ctx.settings, "writer")
        manual_judge = is_manual(ctx.settings, "judge")
        classify = None if manual_judge else teacher_classifier(ctx)
        if writer.count("trigger") == 0:
            propose = None if manual_writer else teacher_slot_values(ctx, home_data)
            fixed += trigger_sentences(ctx, home_data, rng, classify, propose, manual_judge)
        if writer.count("intent") == 0:
            fixed += native_sentences(ctx, home_data, rng)
        if writer.count("custom") == 0:
            fixed += custom_sentences(ctx, home_data, rng, classify)
        fallback = ctx.settings["fallback_topic"]
        if writer.count("chat") == 0 and fallback in ctx.config.topics:
            fixed += [(text, fallback, "chat") for text in ctx.pack.CHAT]
        unclear = next((t.name for t in ctx.config.topics.values() if t.unclear), None)
        if writer.count("gibberish") == 0 and unclear:
            fixed += [
                (text, unclear, "gibberish") for text in gibberish(ctx, rng, settings["gibberish"])
            ]
        for topic in ctx.config.topics.values():  # the topics' own examples (also in the prompt)
            fixed += [(text, topic.name, "example") for text in topic.examples]
        rejected = 0
        for text, topic, source in fixed:
            if holdout.match(text):
                rejected += 1
                continue
            writer.write(
                {"role": "router", "part": source, "text": text, "topic": topic, "source": source}
            )
        progress("router", "templates", len(writer.seen), len(writer.seen), rejected)

        if manual_writer:  # the writer works by hand: its sentences come with the handoff
            print("writer: manual - paraphrases, contrast pairs and knowledge questions come "
                  "from router-trainer handoff export/import writer", flush=True)  # fmt: skip
        else:
            paraphrases(ctx, writer, holdout, home_data, checker)
            if checker is not None:  # sentences on both sides of the borders that get mixed up
                labels.contrast(ctx, writer, holdout, checker, home_data)
            exclude = {normalize(p) for p in (ctx.tests().get("wiki") or {}).values()}
            titles = wikipedia_titles(
                ctx.ws.generated / "wiki_titles.json",
                settings["knowledge"] * 2,
                exclude,
                ctx.config.wikipedia_language,
            )
            knowledge(ctx, writer, holdout, titles)
        if settings["log_questions"]:
            log_questions(ctx, writer, holdout)
        # real speech: the home's own recordings, then natural questions through Piper and
        # Whisper (the errors speech recognition really makes)
        from . import speech

        try:
            speech.recordings(ctx, writer, holdout)
            speech.asr_noise(ctx, writer, holdout)
        except OSError as err:  # the home server is off or Piper/Whisper are not there
            print(f"!! speech sources skipped - {err}", flush=True)
    return out
