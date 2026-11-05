import math

import pytest

from ambilight_hue_sync.protocol import packet
from ambilight_hue_sync.smoothing import smooth_step

C = (0.12, 0.25, 0.18)
DT = 1 / 25


def test_rise_faster_than_fall():
    up = smooth_step((0.3, 0.3, 0.5), (0.3, 0.3, 1.0), DT, C, 0.04)[2] - 0.5
    down = 0.5 - smooth_step((0.3, 0.3, 0.5), (0.3, 0.3, 0.0), DT, C, 0.04)[2]
    assert up == pytest.approx(0.5 * (1 - math.exp(-DT / 0.12)))
    assert down == pytest.approx(0.5 * (1 - math.exp(-DT / 0.25)))
    assert up > down


def test_converges_to_target():
    cur = (0.3, 0.3, 0.0)
    for _ in range(200):
        cur = smooth_step(cur, (0.6, 0.35, 0.8), DT, C, 0.04)
    assert cur == pytest.approx((0.6, 0.35, 0.8), abs=1e-4)


def test_below_dark_targets_zero():
    cur = (0.3, 0.3, 0.5)
    for _ in range(300):
        cur = smooth_step(cur, (0.3, 0.3, 0.03), DT, C, 0.04)
    assert cur[2] == pytest.approx(0.0, abs=1e-6)


def test_colour_jumps_when_waking_from_black():
    x, y, _ = smooth_step((0.32, 0.33, 0.0), (0.7, 0.3, 1.0), DT, C, 0.04)
    assert (x, y) == (0.7, 0.3)


def test_packet_layout():
    cfg_id = "0" * 36
    p = packet(258, cfg_id, {"a": (1.0, 0.5, 0.0), "b": (2.0, -1.0, 1.0)}, {"a": 0, "b": 3})
    assert p[:9] == b"HueStream"
    assert p[9:16] == bytes([2, 0, 2, 0, 0, 1, 0])  # seq wraps at 256
    assert p[16:52] == cfg_id.encode()
    body = p[52:]
    assert len(body) == 14
    assert body[:7] == bytes([0]) + (65535).to_bytes(2, "big") + (32767).to_bytes(2, "big") + b"\x00\x00"
    assert body[7:] == bytes([3]) + (65535).to_bytes(2, "big") + b"\x00\x00" + (65535).to_bytes(2, "big")
