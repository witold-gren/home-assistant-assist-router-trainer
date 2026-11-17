"""Home snapshot: exposed entities with aliases, areas, floors, scripts and scenes.

Taken from Home Assistant with the router repository's ``snapshot_data.home`` - the same data
the control test uses - and saved to workspace/home/snapshot.json. Commands are planned from
it; the control prompt (areas, domains, actions) is built from it too.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from ..context import Context
from .common import stage


def take(ctx: Context) -> dict[str, Any]:
    stage("snapshot")
    url = ctx.settings["home_assistant"]["url"].rstrip("/")
    home = ctx.integ.snapshot_data.home(url, ctx.token())
    out = {
        "taken": datetime.now().isoformat(timespec="minutes"),
        "home": home,
        "fingerprint": ctx.integ.fingerprint(ctx.config, home),
    }
    ctx.ws.snapshot.parent.mkdir(parents=True, exist_ok=True)
    ctx.ws.snapshot.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"home: {len(home['targets'])} exposed entities, {len(home['areas'])} area names, "
        f"{len(home['actions'])} scripts and scenes",
        flush=True,
    )
    return out
