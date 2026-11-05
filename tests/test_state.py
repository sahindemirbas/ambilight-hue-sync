from ambilight_hue_sync.state import (TvHealth, build_snapshot, keep_existing_snapshot, light_ids,
                                      resolve_channels, restore_body)

DEVICES = {"d1": "Strip", "d2": "Lamp", "d3": "Other"}


def light(lid, dev, **kw):
    d = {"id": lid, "owner": {"rid": dev}, "on": {"on": kw.pop("on", True)}}
    d.update(kw)
    return d


def test_resolve_channels():
    cfg = {"channels": [{"channel_id": 0, "members": [{"service": {"rid": "e1"}}]},
                        {"channel_id": 1, "members": [{"service": {"rid": "e2"}}]}]}
    assert resolve_channels(cfg, {"e1": "d1", "e2": "d2"}, DEVICES) == {"Strip": 0, "Lamp": 1}


def test_snapshot_prefers_valid_mirek_then_xy():
    lights = [
        light("l1", "d1", dimming={"brightness": 40.0},
              color_temperature={"mirek": 366, "mirek_valid": True}, color={"xy": {"x": 0.4, "y": 0.4}}),
        light("l2", "d2", on=False, dimming={"brightness": 80.0},
              color_temperature={"mirek": None, "mirek_valid": False}, color={"xy": {"x": 0.6, "y": 0.3}}),
        light("l3", "d3"),
    ]
    snap = build_snapshot(lights, DEVICES, ["Strip", "Lamp"])
    assert snap == {"Strip": {"on": True, "brightness": 40.0, "mirek": 366},
                    "Lamp": {"on": False, "brightness": 80.0, "xy": {"x": 0.6, "y": 0.3}}}
    assert light_ids(lights, DEVICES, ["Strip", "Lamp"]) == {"Strip": "l1", "Lamp": "l2"}


def test_restore_body_round_trip():
    assert restore_body({"on": True, "brightness": 40.0, "mirek": 366}) == {
        "on": {"on": True}, "dimming": {"brightness": 40.0}, "color_temperature": {"mirek": 366}}
    assert restore_body({"on": True, "xy": {"x": 0.6, "y": 0.3}}) == {
        "on": {"on": True}, "color": {"xy": {"x": 0.6, "y": 0.3}}}
    # An off light is only switched off; colour writes would turn it back on.
    assert restore_body({"on": False, "brightness": 80.0, "xy": {"x": 0.6, "y": 0.3}}) == {"on": {"on": False}}


def test_keep_snapshot_after_crash_mid_stream():
    streaming = [light("l1", "d1", mode="streaming")]
    normal = [light("l1", "d1", mode="normal")]
    assert keep_existing_snapshot(streaming, True)
    assert not keep_existing_snapshot(streaming, False)
    assert not keep_existing_snapshot(normal, True)


def test_tv_off_after_three_failures_and_slow_polling():
    h = TvHealth(interval=0.15, safe_interval=0.4)
    h.ok()
    assert h.on and h.next_interval(0) == 0.15
    assert h.fail(100) == 3 and h.on
    assert h.fail(101) == 6 and h.on
    assert h.fail(102) == 9 and not h.on
    assert h.next_interval(150) == 0.4
    assert h.next_interval(163) == 0.15
    h.ok()
    assert h.on and h.fails == 0
    for _ in range(20):
        backoff = h.fail(200)
    assert backoff == 30
