"""Writing language pack YAML: the tags the packs read (``!tuple``, ``!set``, ``!frozenset``),
every value in full (no anchors), short lists on one line, longer texts as blocks - the layout
of the shipped packs, so a translated draft reads like them."""

from __future__ import annotations

from typing import Any

import yaml


class PackDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # every value written out in full
        return True


def _short(items: list[Any]) -> bool:
    texts = [str(i) for i in items]
    return all(not isinstance(i, (list, tuple, dict)) for i in items) and (
        sum(len(t) + 2 for t in texts) < 60 or all(len(t) < 16 for t in texts)
    )


def _sequence(tag: str, order=list):
    def represent(dumper: yaml.SafeDumper, data: Any) -> yaml.Node:
        items = order(data)
        return dumper.represent_sequence(tag, items, flow_style=_short(items))

    return represent


def _text(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    # a block scalar keeps one final newline at most (more would need "|+" and a "..." marker)
    style = ('"' if data.endswith("\n\n") else "|") if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


PackDumper.add_representer(tuple, _sequence("!tuple"))
PackDumper.add_representer(list, _sequence("tag:yaml.org,2002:seq"))
PackDumper.add_representer(set, _sequence("!set", sorted))
PackDumper.add_representer(frozenset, _sequence("!frozenset", sorted))
PackDumper.add_representer(str, _text)


def dump_value(value: Any) -> str:
    return yaml.dump(value, Dumper=PackDumper, allow_unicode=True, width=100, sort_keys=False,
                     default_flow_style=False)  # fmt: skip


def dump_entry(name: str, value: Any, comment: str | None = None) -> str:
    """One top-level entry with its comment above it."""
    text = yaml.dump({name: value}, Dumper=PackDumper, allow_unicode=True, width=100,
                     sort_keys=False, default_flow_style=False)  # fmt: skip
    lines = [f"# {line}" for line in (comment or "").splitlines() if line.strip()]
    return "".join(f"{line}\n" for line in lines) + text
