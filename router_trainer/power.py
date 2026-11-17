"""The GPU machine switched on and off through Home Assistant (as in home-assistant-wakeword).

Home Assistant keeps a switch for the machine that does the whole job (an example package:
``docs/home-assistant/maszyna_gpu.yaml``): on = its smart plug on (the BIOS starts the machine when
power comes back); off = the system shut down over SSH, then - only when the plug measures less
than a few watts - the plug switched off. The panel only flips that switch and shows the state:
off, starting (on, the SSH port not answering yet), on, stopping (off, the plug still drawing
power).

Settings next to the panel's Home Assistant connection (``workspace/home_assistant.json``, key
``"power"``): the machine's switch, the plug's power sensor, the "off" threshold.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from .config import Workspace, read_ha_file, write_ha_file

ENTITY_PATTERN = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


@dataclass
class PowerSettings:
    switch: str = ""  # the machine's switch in Home Assistant, e.g. switch.maszyna_gpu
    sensor: str = ""  # the plug's power in W, e.g. sensor.komputer_gpu_gniazdko_moc
    off_watts: float = 5.0  # below: the machine is really off

    @property
    def ready(self) -> bool:
        return bool(self.switch and self.sensor)

    def validate(self) -> None:
        for name, domains in (("switch", ("switch", "input_boolean")), ("sensor", ("sensor",))):
            value = getattr(self, name)
            if value and (not ENTITY_PATTERN.match(value) or value.split(".")[0] not in domains):
                raise ValueError(
                    f"{name}: an entity id of {' / '.join(domains)}, e.g. {domains[0]}.name"
                )
        try:
            watts = float(self.off_watts)
        except (TypeError, ValueError):
            raise ValueError("power threshold: 0-100 W") from None
        if not 0 < watts <= 100:
            raise ValueError("power threshold: 0-100 W")


def load_power(ws: Workspace) -> PowerSettings:
    try:
        saved = read_ha_file(ws).get("power") or {}
    except ValueError:  # a broken file: nothing set up
        saved = {}
    known = PowerSettings.__dataclass_fields__
    return PowerSettings(**{k: v for k, v in saved.items() if k in known})


def save_power(ws: Workspace, settings: PowerSettings) -> None:
    settings.validate()
    settings.off_watts = float(settings.off_watts)
    write_ha_file(ws, {**read_ha_file(ws), "power": asdict(settings)})


def machine_state(client: Any, settings: PowerSettings, reachable: bool | None) -> dict[str, Any]:
    """{"switch": on/off/unavailable, "watts", "machine": off/starting/on/stopping/unknown}."""
    switch = client.entity_state(settings.switch).get("state", "unavailable")
    try:
        watts = float(client.entity_state(settings.sensor)["state"])
    except (ValueError, KeyError, TypeError):
        watts = None  # "unavailable", "unknown"
    drawing = watts is not None and watts >= settings.off_watts
    if switch == "on":
        machine = "on" if reachable else "starting"
    elif switch == "off":
        machine = "stopping" if drawing else "off"
    else:
        machine = "unknown"
    return {"switch": switch, "watts": watts, "machine": machine}


def switch_machine(client: Any, settings: PowerSettings, on: bool) -> None:
    domain = settings.switch.split(".")[0]
    client.call_service(domain, "turn_on" if on else "turn_off", settings.switch)
