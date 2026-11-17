"""What the job log says: stages, generation counters, training metrics, test results.

The steps print marker lines (``==> stage``, ``@@progress``, ``@@info``, ``@@metric``,
``@@result``); everything else is shown as plain log text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any

MARKERS = {"@@progress": "progress", "@@metric": "metric", "@@info": "info", "@@result": "result"}
STAGE = re.compile(r"^==> (.+)$")
ERROR = re.compile(r"^(!!|Traceback|[A-Za-z_.]*Error:|SystemExit)")
MAX_POINTS = 2000


@dataclass
class Progress:
    stages: list[str] = field(default_factory=list)
    counters: dict[str, dict[str, Any]] = field(default_factory=dict)  # role/part -> counts
    metrics: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)  # part -> scores
    errors: list[str] = field(default_factory=list)

    @property
    def stage(self) -> str | None:
        return self.stages[-1] if self.stages else None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage"] = self.stage
        data["metrics"] = thin(self.metrics)
        data["errors"] = self.errors[-8:]
        return data


def thin(points: list[dict[str, Any]], limit: int = 400) -> list[dict[str, Any]]:
    """At most ``limit`` points for the chart (every eval point kept)."""
    if len(points) <= limit:
        return points
    step = len(points) / limit
    kept = {int(i * step) for i in range(limit)}
    return [p for i, p in enumerate(points) if i in kept or "eval_loss" in p]


def clean_lines(text: str) -> list[str]:
    """Lines as a terminal shows them (progress bars rewrite a line with \\r)."""
    return [line.rsplit("\r", 1)[-1] for line in text.split("\n")]


def parse(text: str) -> Progress:
    progress = Progress()
    for line in clean_lines(text):
        line = line.strip()
        if not line:
            continue
        if match := STAGE.match(line):
            progress.stages.append(match.group(1))
            continue
        tag, _, payload = line.partition(" ")
        kind = MARKERS.get(tag)
        if kind:
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if kind == "progress":
                progress.counters[f"{data['role']}/{data['part']}"] = data
            elif kind == "metric":
                if len(progress.metrics) < MAX_POINTS * 10:
                    progress.metrics.append(data)
            elif kind == "info":
                progress.info.update(data)
            elif kind == "result":
                progress.results[data["part"]] = data
            continue
        if ERROR.match(line):
            progress.errors.append(line[:300])
    return progress


def tail(text: str, lines: int = 200) -> str:
    """Last lines without the marker lines (they are drawn, not printed)."""
    shown = [
        line for line in clean_lines(text) if line.strip() and line.split(" ", 1)[0] not in MARKERS
    ]
    return "\n".join(shown[-lines:])
