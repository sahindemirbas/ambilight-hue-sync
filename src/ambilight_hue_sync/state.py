"""Light snapshot / restore and TV on/off tracking. Pure, no I/O."""
from __future__ import annotations

from dataclasses import dataclass


def resolve_channels(cfg: dict, entertainment: dict, devices: dict) -> dict:
    """Map device name to channel id for one entertainment configuration.

    ``entertainment`` maps entertainment service id to owning device id,
    ``devices`` maps device id to its display name (CLIP v2).
    """
    chan = {}
    for ch in cfg["channels"]:
        for mem in ch["members"]:
            chan[devices[entertainment[mem["service"]["rid"]]]] = ch["channel_id"]
    return chan


def light_ids(lights: list, devices: dict, wanted) -> dict:
    """Return {name: light id} for the lights we stream to."""
    return {devices[l["owner"]["rid"]]: l["id"] for l in lights
            if devices.get(l["owner"]["rid"]) in wanted}


def keep_existing_snapshot(lights: list, snapshot_exists: bool) -> bool:
    """If a light is still in streaming mode a previous run died mid stream.

    Its current state is the stream colour, not the user's, so the older
    snapshot on disk must be kept rather than overwritten.
    """
    return snapshot_exists and any(l.get("mode") == "streaming" for l in lights)


def build_snapshot(lights: list, devices: dict, wanted) -> dict:
    """Record on/off, brightness and either colour temperature or xy."""
    snap = {}
    for l in lights:
        name = devices.get(l["owner"]["rid"])
        if name not in wanted:
            continue
        st = {"on": l["on"]["on"]}
        if l.get("dimming"):
            st["brightness"] = l["dimming"]["brightness"]
        ct = l.get("color_temperature") or {}
        if ct.get("mirek") and ct.get("mirek_valid"):
            st["mirek"] = ct["mirek"]
        elif l.get("color", {}).get("xy"):
            st["xy"] = l["color"]["xy"]
        snap[name] = st
    return snap


def restore_body(st: dict) -> dict:
    """CLIP v2 PUT body that puts a light back the way it was."""
    body = {"on": {"on": st["on"]}}
    if st["on"]:
        if "brightness" in st:
            body["dimming"] = {"brightness": st["brightness"]}
        if "mirek" in st:
            body["color_temperature"] = {"mirek": st["mirek"]}
        elif "xy" in st:
            body["color"] = {"xy": st["xy"]}
    return body


@dataclass
class TvHealth:
    """Decide when the TV counts as off and how fast to poll it.

    Three failed reads in a row mean the TV is off or asleep. Any failure
    also drops polling to the safe interval for a while, because hammering a
    struggling TV API is what pushes it into its broken 404/403 state.
    """
    interval: float = 0.15
    safe_interval: float = 0.4
    off_after: int = 3
    slow_for: float = 60.0
    fails: int = 0
    slow_until: float = 0.0
    on: bool = False

    def ok(self) -> None:
        self.fails = 0
        self.on = True

    def fail(self, now: float) -> float:
        """Register a failure; return how long to back off (seconds)."""
        self.fails += 1
        self.slow_until = now + self.slow_for
        if self.fails >= self.off_after:
            self.on = False
        return min(30, 3 * self.fails)

    def next_interval(self, now: float) -> float:
        return self.safe_interval if now < self.slow_until else self.interval
