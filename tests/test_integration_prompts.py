"""Training chats are built with the integration's own functions - what HA sends."""

from __future__ import annotations

import json

from tests.conftest import needs_router

pytestmark = needs_router


def test_router_chat_is_the_integrations_request(ctx) -> None:
    from custom_components.assist_router.router import OllamaSettings, build_request

    request = build_request(OllamaSettings("u", "m", 1, 1), ctx.config, "Co Ola ma jutro?")
    assert ctx.integ.router_messages(ctx.config, "Co Ola ma jutro?") == request["messages"]
    assert ctx.integ.router_schema(ctx.config) == request["format"]
    assert json.loads(ctx.integ.router_answer("kalendarz")) == {"temat": "kalendarz"}


def test_control_answer_has_every_schema_key_in_order(ctx, home_data) -> None:
    answer = ctx.integ.control_answer(
        home_data, {"intent": "HassTurnOff", "domain": "light", "area": "Kuchnia"}
    )
    data = json.loads(answer)
    schema = ctx.integ.control_schema(home_data)
    assert list(data) == list(schema["properties"])
    assert data["intencja"] == "HassTurnOff" and data["obszar"] == "Kuchnia"
    assert data["wszystkie"] is False and data["radio"] is False and data["nazwa"] is None
    # the integration reads it back to the same command
    command = ctx.integ.parse_command(home_data, answer)
    assert (command.intent, command.domain, command.area) == ("HassTurnOff", "light", "Kuchnia")


def test_control_messages_apply_the_speech_fixes(ctx, home_data) -> None:
    from custom_components.assist_router.control import prepare_text

    messages = ctx.integ.control_messages(home_data, ctx.config.household, "zapasz kawę")
    assert messages[0]["role"] == "system" and "Ekspres - zrób kawę" in messages[0]["content"]
    assert ctx.config.household in messages[0]["content"]
    assert messages[1]["content"] == prepare_text("zapasz kawę")[0]


def test_answer_and_summary_messages(ctx) -> None:
    from datetime import datetime

    messages = ctx.integ.answer_messages(
        ctx.config, datetime(2026, 3, 2, 9, 5), "Kalendarz: basen", "Co jest dziś?", "Ola", "hint"
    )
    assert messages[0]["content"].endswith("Kalendarz: basen")
    assert "Ola" in messages[0]["content"] and "hint" in messages[0]["content"]
    summary = ctx.integ.summary_messages(ctx.config, "Artykuł o czymś.", "Co to?")
    assert summary[1]["content"] == "Co to?"


def test_fingerprint_follows_prompts(ctx, home_data) -> None:
    first = ctx.integ.fingerprint(ctx.config, home_data)
    assert first == ctx.integ.fingerprint(ctx.config, home_data)
    home_data["areas"]["Garaż"] = "Garaż"
    assert ctx.integ.fingerprint(ctx.config, home_data) != first
    assert ctx.integ.fingerprint(ctx.config, None) != first
