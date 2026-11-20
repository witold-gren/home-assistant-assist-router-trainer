"""Language packs of the trainer: teacher prompts and vocabulary for made-up data.

The pack is chosen by the integration's language (``LANG.CODE`` of the Assist Router pack in
use), so data are generated in the language the integration speaks. A pack is a folder named
after the language code (``pl/``), laid out like Assist Router's packs:

- ``texts.yaml``: the teacher prompts as ``str.format`` templates and the JSON keys;
- ``words.yaml``: styles, chat, gibberish, made-up data, Whisper hallucinations, inflection rules;
- ``grammar.py``: the functions that fill the templates and build made-up data (it runs with
  every name of the YAML files already defined).

Another language = a copy of the folder, translated (docs: "A new language"); ``problems``
lists what a new pack still lacks, ``router-trainer languages --check CODE`` prints it.
"""

from __future__ import annotations

from pathlib import Path
import re
import string
from types import ModuleType
from typing import Any

import yaml

FOLDER = Path(__file__).parent
DATA_FILES = ("texts.yaml", "words.yaml")
GRAMMAR_FILE = "grammar.py"
REFERENCE = "pl"


class PackLoader(yaml.SafeLoader):
    """YAML of a language pack: ``!tuple``, ``!set``, ``!frozenset`` and ``!translate``."""


def _sequence(kind):
    def construct(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        return kind(loader.construct_sequence(node, deep=True))

    return construct


def _translate(loader: yaml.SafeLoader, node: yaml.Node) -> dict[int, int]:
    data = loader.construct_mapping(node)
    return str.maketrans(str(data["from"]), str(data["to"]))


PackLoader.add_constructor("!tuple", _sequence(tuple))
PackLoader.add_constructor("!set", _sequence(set))
PackLoader.add_constructor("!frozenset", _sequence(frozenset))
PackLoader.add_constructor("!translate", _translate)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=PackLoader)
    if data is not None and not isinstance(data, dict):
        raise ValueError(f"{path}: a mapping of names is expected")
    return data or {}


def load_pack(folder: Path, name: str | None = None) -> ModuleType:
    """The pack in ``folder`` as one module: the YAML names, then grammar.py run on top."""
    module = ModuleType(name or f"{__name__}.{folder.name}")
    module.__file__ = str(folder / GRAMMAR_FILE)
    for file in DATA_FILES:
        module.__dict__.update(read_yaml(folder / file))
    grammar = folder / GRAMMAR_FILE
    if grammar.is_file():
        code = compile(grammar.read_text(encoding="utf-8"), str(grammar), "exec")
        exec(code, module.__dict__)
    return module


def available() -> list[str]:
    return sorted(
        path.name
        for path in FOLDER.iterdir()
        if path.is_dir() and not path.name.startswith("_") and (path / DATA_FILES[0]).is_file()
    )


_PACKS: dict[str, ModuleType] = {}


def get(code: str) -> ModuleType:
    if code not in available():
        raise ValueError(f"no trainer language pack {code!r} (available: {', '.join(available())})")
    if code not in _PACKS:
        _PACKS[code] = load_pack(FOLDER / code)
    return _PACKS[code]


def names(pack: ModuleType) -> set[str]:
    """The public names a pack defines itself (not what it imports)."""
    import __future__

    out = set()
    for name, value in vars(pack).items():
        if name.startswith("_") or isinstance(value, (ModuleType, __future__._Feature)):
            continue
        if callable(value) and getattr(value, "__module__", "") != pack.__name__:
            continue  # imported functions and classes
        out.add(name)
    return out


def missing(code: str) -> list[str]:
    """Names of the reference pack (``pl``) that the pack ``code`` does not define yet."""
    return sorted(names(get(REFERENCE)) - names(get(code)))


def fields(text: str) -> set[str]:
    try:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}
    except ValueError:
        return {"<broken braces>"}


def problems(folder: Path, reference: Path | None = None) -> list[str]:
    """Everything wrong with the pack in ``folder`` against the reference (empty = ready)."""
    reference = reference or FOLDER / REFERENCE
    try:
        pack = load_pack(folder, f"trainer_pack_check.{folder.name}")
    except Exception as err:  # the files themselves are broken
        return [f"the pack does not load: {type(err).__name__}: {err}"]
    ref = load_pack(reference, f"trainer_pack_check.ref_{reference.name}")
    out = [f"missing: {name}" for name in sorted(names(ref) - names(pack))]
    own = read_yaml(folder / "texts.yaml")
    for name, text in read_yaml(reference / "texts.yaml").items():
        mine = own.get(name)
        if isinstance(text, str) and isinstance(mine, str) and fields(text) != fields(mine):
            out.append(
                f"texts.yaml {name}: fields {sorted(fields(mine))}, expected {sorted(fields(text))}"
            )
    for name, value in vars(ref).items():
        mine = getattr(pack, name, None)
        if isinstance(value, re.Pattern) and not isinstance(mine, re.Pattern):
            out.append(f"{name}: a pattern is expected")
    try:  # every prompt fills in
        pack.paraphrase_prompt("h", "t", "d", ["e"], 3, "s", "")
        pack.contrast_prompt("h", [("a", "x", []), ("b", "y", ["e"])], 3, "s", "")
        pack.facts_prompt("q", "source")
        pack.slot_values_prompt("kto", ["t"], "h", "r", "d")
        pack.command_prompt(["d"], 3, "s")
        pack.knowledge_prompt(["t"])
    except Exception as err:
        out.append(f"a prompt does not fill in: {type(err).__name__}: {err}")
    return out
