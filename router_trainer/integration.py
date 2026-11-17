"""The only place that imports the Assist Router integration.

Training examples are built with the integration's own functions - the router prompt and
schema, the command parser prompt and schema, the answer and summary prompts - so a trained
model sees exactly what Home Assistant sends it. Nothing here copies a prompt.

The integration imports Home Assistant, so this module needs the environment made by
scripts/setup.sh (the router repository's test requirements).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import yaml


@dataclass
class Integration:
    """Modules of the router repository: the integration and its test tools."""

    repo: Path
    lang: ModuleType
    router: ModuleType
    control: ModuleType
    benchmark: ModuleType
    snapshot_data: ModuleType
    topic_data: ModuleType

    # --- router.yaml ------------------------------------------------------------------------

    def parse_config(self, data: dict[str, Any]) -> Any:
        return self.router.parse_config(data)

    def load_config(self, path: Path) -> Any:
        return self.parse_config(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    # --- the router role ----------------------------------------------------------------------

    def router_messages(self, config: Any, question: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.router.build_system_prompt(config)},
            {"role": "user", "content": question},
        ]

    def router_answer(self, topic: str) -> str:
        """The model's reply as Ollama returns it with the schema: {"temat": "..."}."""
        return json.dumps({self.lang.TOPIC_KEY: topic}, ensure_ascii=False)

    def router_schema(self, config: Any) -> dict[str, Any]:
        return self.router.build_schema(config)

    # --- the control role ---------------------------------------------------------------------

    def home(self, home_data: dict[str, Any]) -> Any:
        return self.control.home_from_dict(home_data)

    def control_system(self, home_data: dict[str, Any], household: str) -> str:
        return self.control.build_control_prompt(
            self.home(home_data), household, home_data.get("actions")
        )

    def control_messages(
        self, home_data: dict[str, Any], household: str, text: str
    ) -> list[dict[str, str]]:
        """System prompt and the command as the integration sends them (speech fixes applied)."""
        prepared, _ = self.control.prepare_text(text)
        return [
            {"role": "system", "content": self.control_system(home_data, household)},
            {"role": "user", "content": prepared},
        ]

    def control_schema(self, home_data: dict[str, Any]) -> dict[str, Any]:
        return self.control.build_control_schema(self.home(home_data))

    def control_answer(self, home_data: dict[str, Any], fields: dict[str, Any]) -> str:
        """The parser's reply for ``fields`` (English keys): every key of the schema, in the
        schema's order, with the language pack's JSON keys."""
        keys = self.lang.CONTROL_KEYS
        defaults = {"all": False, "radio": False}
        properties = self.control_schema(home_data)["properties"]
        english = {json_key: key for key, json_key in keys.items()}
        out = {}
        for json_key in properties:
            key = english[json_key]
            out[json_key] = fields.get(key, defaults.get(key))
        return json.dumps(out, ensure_ascii=False)

    def parse_command(self, home_data: dict[str, Any], content: str) -> Any:
        return self.control.parse_command(self.home(home_data), content)

    def find_target(self, home_data: dict[str, Any], command: Any, text: str) -> Any:
        return self.control.find_target(self.home(home_data), command, text)

    # --- the answer role ----------------------------------------------------------------------

    def answer_messages(
        self,
        config: Any,
        now: datetime,
        data: str,
        question: str,
        speaker: str | None = None,
        hint: str = "",
    ) -> list[dict[str, str]]:
        return self.router.answer_messages(config, now, data, question, speaker, hint)

    def summary_messages(self, config: Any, article: str, question: str) -> list[dict[str, str]]:
        return self.router.summary_messages(config, article, question)

    # --- what a trained model depends on --------------------------------------------------------

    def fingerprint(self, config: Any, home_data: dict[str, Any] | None) -> str:
        """Hash of every prompt part a model learns: router prompt and topics, parser prompt
        and schema, answer and summary prompts. A different hash = the training data no longer
        matches what the integration sends (router.yaml or the home changed)."""
        parts = [
            self.router.build_system_prompt(config),
            json.dumps(self.router.build_schema(config), sort_keys=True),
            config.answer_prompt or self.lang.ANSWER_PROMPT,
            config.summary_prompt or self.lang.SUMMARY_PROMPT,
            config.household,
        ]
        if home_data:
            parts.append(self.control_system(home_data, config.household))
            parts.append(json.dumps(self.control_schema(home_data), sort_keys=True))
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def load(repo: Path) -> Integration:
    """Import the integration and its tools from the router repository."""
    repo = Path(repo).resolve()
    if not (repo / "custom_components" / "assist_router").is_dir():
        raise FileNotFoundError(
            f"{repo} is not the Assist Router repository (router_repo in trainer.yaml)"
        )
    for path in (repo, repo / "tools"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from custom_components.assist_router import control, router
    from custom_components.assist_router.languages import LANG
    import model_benchmark
    import snapshot_data
    import topic_data

    return Integration(repo, LANG, router, control, model_benchmark, snapshot_data, topic_data)
