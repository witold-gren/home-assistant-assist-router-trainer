"""Try one sentence on several models side by side (the panel's "Try it" box).

Every model gets what the integration would send: the router prompt first, then - by the topic
it chose - the command parser prompt, or the answer prompt with your live HA data. Nothing is
executed in Home Assistant; data are only read.
"""

from __future__ import annotations

from datetime import datetime
import json
import time
from typing import Any
from zoneinfo import ZoneInfo

from .context import Context

ANSWER_TOKENS = 160


def _chat(ctx: Context, body: dict[str, Any]) -> tuple[str, float]:
    started = time.monotonic()
    result, _ = ctx.integ.benchmark.chat(ctx.settings["ollama"]["jetson"].rstrip("/"), body)
    return result.get("message", {}).get("content", ""), time.monotonic() - started


def try_model(ctx: Context, model: str, text: str, home_now: Any) -> dict[str, Any]:
    config = ctx.config
    content, seconds = _chat(
        ctx,
        {
            "model": model,
            "stream": False,
            "keep_alive": "10m",
            "format": ctx.integ.router_schema(config),
            "options": {"temperature": 0, "num_predict": 30, "num_ctx": 8192},
            "messages": ctx.integ.router_messages(config, text),
        },
    )
    route = ctx.integ.router.parse_route(config, content, text)
    out: dict[str, Any] = {"topic": route.topic if route else None, "router_s": round(seconds, 2)}
    if route is None:
        out["raw"] = content
        return out
    topic = config.topics[route.topic]
    if topic.control:
        home_data = ctx.home_data()
        content, seconds = _chat(
            ctx,
            {
                "model": model,
                "stream": False,
                "keep_alive": "10m",
                "format": ctx.integ.control_schema(home_data),
                "options": {"temperature": 0, "num_predict": 160, "num_ctx": 8192},
                "messages": ctx.integ.control_messages(home_data, config.household, text),
            },
        )
        command = ctx.integ.parse_command(home_data, content)
        match = ctx.integ.find_target(home_data, command, text) if command else None
        out.update(
            control=json.loads(content) if content.strip().startswith("{") else content,
            device=match.target.name if match and match.target else None,
            control_s=round(seconds, 2),
        )
    elif home_now is not None and (topic.entities or topic.details or topic.fetch):
        tz = ZoneInfo(ctx.settings["home_assistant"]["time_zone"])
        now = datetime.now(tz).replace(second=0, microsecond=0)
        entry = ctx.integ.topic_data.topic_data(home_now, config, topic.name, text, None, now)
        messages = ctx.integ.answer_messages(
            config, now, entry["data"], text, entry["speaker"], entry["hint"]
        )
        content, seconds = _chat(
            ctx,
            {
                "model": model,
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0.2,
                    "num_predict": topic.answer_tokens or ANSWER_TOKENS,
                    "num_ctx": 8192,
                },
                "messages": messages,
            },
        )
        out.update(answer=" ".join(content.split()), answer_s=round(seconds, 2))
    return out


def try_text(ctx: Context, text: str, models: list[str]) -> dict[str, Any]:
    home_now = None
    try:
        topic_data = ctx.integ.topic_data
        ha = ctx.settings["home_assistant"]
        home_now = topic_data.load_home(topic_data.HA(ha["url"], ctx.token()))
    except Exception as err:
        print(f"!! no HA data: {err}", flush=True)
    return {"text": text, "models": {m: try_model(ctx, m, text, home_now) for m in models}}
