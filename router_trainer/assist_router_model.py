"""The router model of Assist Router in Home Assistant, changed from the studio.

Through Assist Router's own options flow (Settings → Assist Router → Configure → Router
model) over Home Assistant's REST API: open the options, pick the "router" step, send the
form with the values it shows and only the router model changed. Home Assistant checks the
form as when it is filled in by hand - a model that is not in the home Ollama is refused.

The model used before is kept in ``auto/router_model.json``, so "Restore" puts it back.
"""

from __future__ import annotations

import json
from typing import Any

from .config import Workspace
from .ha_client import Client, HaError

DOMAIN = "assist_router"
STEP = "router"
FIELD = "router_model"
FLOW = "/config/config_entries/options/flow"


def _call(client: Client, path: str, data: dict[str, Any] | None = None, method: str = "GET"):
    body = None if data is None else json.dumps(data).encode()
    with client._open(path, data=body, method=method) as response:
        text = response.read().decode("utf-8")
    return json.loads(text) if text else None


def entry_id(client: Client) -> str:
    entries = _call(client, f"/config/config_entries/entry?domain={DOMAIN}") or []
    loaded = [e for e in entries if e.get("state") == "loaded"] or entries
    if not loaded:
        raise HaError("Assist Router is not set up in Home Assistant")
    return loaded[0]["entry_id"]


def form_values(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The values a form shows (defaults and suggested values) and the choices of the router
    model field."""
    values: dict[str, Any] = {}
    choices: list[str] = []
    for field in form.get("data_schema") or []:
        name = field.get("name")
        if "default" in field:
            values[name] = field["default"]
        elif (suggested := (field.get("description") or {}).get("suggested_value")) is not None:
            values[name] = suggested
        if name == FIELD:
            options = ((field.get("selector") or {}).get("select") or {}).get("options") or []
            choices = [o["value"] if isinstance(o, dict) else str(o) for o in options]
    return values, choices


def _open_router_step(client: Client) -> tuple[str, dict[str, Any]]:
    flow = _call(client, FLOW, {"handler": entry_id(client)}, "POST")
    flow_id = flow["flow_id"]
    if flow.get("type") == "menu":
        flow = _call(client, f"{FLOW}/{flow_id}", {"next_step_id": STEP}, "POST")
    if flow.get("type") != "form" or flow.get("step_id") != STEP:
        _call(client, f"{FLOW}/{flow_id}", method="DELETE")
        raise HaError(f"Assist Router's options did not show the {STEP!r} step")
    return flow_id, flow


def current(client: Client) -> dict[str, Any]:
    """The router model in use and the models Assist Router can choose (the home Ollama)."""
    flow_id, form = _open_router_step(client)
    try:
        values, choices = form_values(form)
    finally:
        _call(client, f"{FLOW}/{flow_id}", method="DELETE")  # nothing is changed
    return {"model": values.get(FIELD), "choices": choices}


def _remember(ws: Workspace, previous: str | None, model: str) -> None:
    path = ws.root / "auto" / "router_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"previous": previous, "model": model}, ensure_ascii=False), encoding="utf-8"
    )


def remembered(ws: Workspace) -> dict[str, Any] | None:
    path = ws.root / "auto" / "router_model.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def use(client: Client, ws: Workspace, model: str) -> dict[str, Any]:
    """Set Assist Router's router model; the one before is remembered for "Restore"."""
    flow_id, form = _open_router_step(client)
    values, choices = form_values(form)
    if model not in choices:
        _call(client, f"{FLOW}/{flow_id}", method="DELETE")
        raise HaError(
            f"{model} is not in the home Ollama - export the run first (Assist Router lists "
            "only the models Ollama has)"
        )
    previous = values.get(FIELD)
    result = _call(client, f"{FLOW}/{flow_id}", {**values, FIELD: model}, "POST")
    if result.get("type") != "create_entry":
        raise HaError(f"Assist Router refused the options: {result.get('errors') or result}")
    if previous != model:
        _remember(ws, previous, model)
    return {"model": model, "previous": previous}


def restore(client: Client, ws: Workspace) -> dict[str, Any]:
    """Put back the router model used before the last "Use in Assist Router"."""
    saved = remembered(ws)
    if not saved or not saved.get("previous"):
        raise ValueError("no earlier router model is remembered")
    result = use(client, ws, saved["previous"])
    (ws.root / "auto" / "router_model.json").unlink(missing_ok=True)
    return result
