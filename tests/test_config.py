import json
import tomllib
from pathlib import Path

import pytest

from ambilight_hue_sync import config

ROOT = Path(__file__).resolve().parents[1]


def example():
    return tomllib.loads((ROOT / "config.example.toml").read_text())


def test_example_config_parses_with_env_secrets(tmp_path):
    env = {"AMBILIGHT_TV_USERNAME": "u", "AMBILIGHT_TV_PASSWORD": "p",
           "AMBILIGHT_HUE_USERNAME": "k", "AMBILIGHT_HUE_CLIENTKEY": "c", "AMBILIGHT_HUE_APPID": "a"}
    cfg = config.parse(example(), env=env, base_dir=tmp_path)
    assert cfg.tv_password == "p" and cfg.hue_clientkey == "c"
    assert len(cfg.lights) >= 1
    assert cfg.fps == 25 and cfg.interval == 0.15


def test_credentials_file_is_read(tmp_path):
    (tmp_path / "hue.json").write_text(json.dumps({"username": "k", "clientkey": "c", "appid": "a"}))
    data = example()
    data["hue"]["credentials_file"] = "hue.json"
    data["tv"].update(username="u", password="p")
    cfg = config.parse(data, env={}, base_dir=tmp_path)
    assert (cfg.hue_username, cfg.hue_clientkey, cfg.hue_appid) == ("k", "c", "a")


def test_missing_secrets_are_reported(tmp_path):
    with pytest.raises(ValueError, match="tv_password"):
        config.parse(example(), env={}, base_dir=tmp_path)


def test_bad_light_rejected(tmp_path):
    data = example()
    data["light"] = [{"name": "x", "side": "diagonal"}]
    with pytest.raises(ValueError, match="side"):
        config.parse(data, env={}, base_dir=tmp_path)


def test_per_light_smoothing_override(tmp_path):
    data = example()
    data["tv"].update(username="u", password="p")
    data["hue"].update(username="k", clientkey="c", appid="a", credentials_file="")
    data["light"] = [{"name": "a", "side": "left", "smoothing": [0.2, 0.3, 0.4]},
                     {"name": "b", "side": "top"}]
    cfg = config.parse(data, env={}, base_dir=tmp_path)
    assert cfg.smoothing_for("a") == (0.2, 0.3, 0.4)
    assert cfg.smoothing_for("b") == config.DEFAULT_SMOOTH
