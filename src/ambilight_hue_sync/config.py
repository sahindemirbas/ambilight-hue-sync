"""Load config.toml, with secrets overridable from the environment."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SIDES = {"left", "right", "top", "bottom", "all"}
DEFAULT_SMOOTH = (0.12, 0.25, 0.18)


@dataclass
class Light:
    name: str
    side: str
    start: float = 0.0
    end: float = 1.0
    scale: float = 1.0
    smoothing: tuple | None = None


@dataclass
class Config:
    tv_host: str
    tv_username: str
    tv_password: str
    hue_host: str
    hue_username: str
    hue_clientkey: str
    hue_appid: str
    area: str
    lights: list[Light]
    top_first: dict = field(default_factory=dict)
    interval: float = 0.15
    safe_interval: float = 0.4
    fps: int = 25
    dark: float = 0.04
    smooth_default: tuple = DEFAULT_SMOOTH
    snapshot_path: Path = Path("~/.cache/ambilight-hue-sync/snapshot.json").expanduser()

    def smoothing_for(self, name: str) -> tuple:
        for lt in self.lights:
            if lt.name == name and lt.smoothing:
                return lt.smoothing
        return self.smooth_default


def default_config_path() -> Path:
    env = os.environ.get("AMBILIGHT_CONFIG")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "ambilight-hue-sync" / "config.toml"


def _secret(env: dict, key: str, section: dict, name: str) -> str:
    return env.get(key) or section.get(name, "")


def parse(data: dict, env: dict | None = None, base_dir: Path | None = None) -> Config:
    """Build a Config from parsed TOML. Raises ValueError on bad input."""
    env = os.environ if env is None else env
    tv, hue = data.get("tv", {}), data.get("hue", {})
    creds = {}
    cpath = hue.get("credentials_file")
    if cpath:
        p = Path(cpath).expanduser()
        if not p.is_absolute() and base_dir:
            p = base_dir / p
        if p.exists():
            creds = json.loads(p.read_text())
    lights = []
    for raw in data.get("light", []):
        lt = Light(name=raw["name"], side=raw["side"], start=float(raw.get("start", 0.0)),
                   end=float(raw.get("end", 1.0)), scale=float(raw.get("scale", 1.0)),
                   smoothing=tuple(raw["smoothing"]) if raw.get("smoothing") else None)
        if lt.side not in SIDES:
            raise ValueError(f"light {lt.name!r}: side must be one of {sorted(SIDES)}")
        if not 0.0 <= lt.start < lt.end <= 1.0:
            raise ValueError(f"light {lt.name!r}: need 0 <= start < end <= 1")
        lights.append(lt)
    if not lights:
        raise ValueError("config needs at least one [[light]] entry")
    cfg = Config(
        tv_host=env.get("AMBILIGHT_TV_HOST") or tv.get("host", ""),
        tv_username=_secret(env, "AMBILIGHT_TV_USERNAME", tv, "username"),
        tv_password=_secret(env, "AMBILIGHT_TV_PASSWORD", tv, "password"),
        hue_host=env.get("AMBILIGHT_HUE_HOST") or hue.get("host", ""),
        hue_username=env.get("AMBILIGHT_HUE_USERNAME") or creds.get("username") or hue.get("username", ""),
        hue_clientkey=env.get("AMBILIGHT_HUE_CLIENTKEY") or creds.get("clientkey") or hue.get("clientkey", ""),
        hue_appid=env.get("AMBILIGHT_HUE_APPID") or creds.get("appid") or hue.get("appid", ""),
        area=hue.get("entertainment_area", ""),
        lights=lights,
        top_first=dict(tv.get("top_first", {})),
        interval=float(tv.get("interval", 0.15)),
        safe_interval=float(tv.get("safe_interval", 0.4)),
        fps=int(hue.get("fps", 25)),
        dark=float(data.get("tuning", {}).get("dark", 0.04)),
        smooth_default=tuple(data.get("tuning", {}).get("smoothing", DEFAULT_SMOOTH)),
    )
    if hue.get("snapshot_file"):
        cfg.snapshot_path = Path(hue["snapshot_file"]).expanduser()
    missing = [k for k in ("tv_host", "tv_username", "tv_password", "hue_host",
                           "hue_username", "hue_clientkey", "hue_appid", "area")
               if not getattr(cfg, k)]
    if missing:
        raise ValueError("missing config values: " + ", ".join(missing))
    return cfg


def load(path: Path | None = None) -> Config:
    path = path or default_config_path()
    with open(path, "rb") as f:
        return parse(tomllib.load(f), base_dir=path.parent)
