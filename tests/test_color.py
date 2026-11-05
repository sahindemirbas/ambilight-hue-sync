import pytest

from ambilight_hue_sync.color import (WHITE_XY, dominant_rgb, frame_targets, pull_dim_to_white,
                                      region, rgb_to_xy, side_pixels)
from ambilight_hue_sync.config import Light


def px(r, g, b):
    return {"r": r, "g": g, "b": b}


def edge(colors):
    return {str(i): c for i, c in enumerate(colors)}


def test_side_pixels_orders_numerically_not_lexically():
    m = {"left": edge([px(i, 0, 0) for i in range(12)])}
    got = side_pixels(m, "left", 0.0, 1.0, {})
    assert [p["r"] for p in got] == list(range(12))


def test_side_pixels_top_first_flips_edge():
    m = {"right": edge([px(i, 0, 0) for i in range(4)])}
    lower_half = side_pixels(m, "right", 0.0, 0.5, {"right": True})
    assert [p["r"] for p in lower_half] == [3, 2]


def test_side_pixels_always_returns_at_least_one():
    m = {"top": edge([px(i, 0, 0) for i in range(4)])}
    assert len(side_pixels(m, "top", 0.9, 0.91, {})) == 1


def test_dominant_hue_beats_average():
    # 6 orange and 4 blue pixels: an average would be a muddy purple.
    pix = [px(255, 128, 0)] * 6 + [px(0, 0, 255)] * 4
    r, g, b = dominant_rgb(pix)
    assert r == pytest.approx(255) and g == pytest.approx(128) and b == pytest.approx(0)


def test_grey_scene_falls_back_to_plain_average():
    pix = [px(100, 100, 100), px(200, 200, 200)]
    assert dominant_rgb(pix) == [150, 150, 150]


def test_hue_wraps_around_red():
    # Hues just below 360 and just above 0 are the same red group.
    pix = [px(255, 0, 20), px(255, 20, 0), px(0, 255, 0)]
    r, g, b = dominant_rgb(pix)
    assert r > 200 and g < 30


def test_region_brightness_uses_channel_max():
    m = {"left": edge([px(255, 0, 0), px(0, 0, 0)])}
    _, v = region(m, "left", 0, 1, {})
    assert v == pytest.approx(0.5)


def test_region_all_and_empty():
    m = {"left": edge([px(0, 0, 255)]), "top": edge([px(0, 0, 255)])}
    rgb, v = region(m, "all", 0, 1, {})
    assert v == pytest.approx(1.0) and rgb[2] == pytest.approx(255)
    assert region({}, "all", 0, 1, {}) == ([0, 0, 0], 0)


def test_rgb_to_xy_reference_points():
    assert rgb_to_xy([0, 0, 0]) == WHITE_XY
    x, y = rgb_to_xy([255, 255, 255])
    assert x == pytest.approx(0.3227, abs=0.01) and y == pytest.approx(0.329, abs=0.01)
    rx, ry = rgb_to_xy([255, 0, 0])
    assert rx > 0.65 and ry < 0.35
    bx, by = rgb_to_xy([0, 0, 255])
    assert bx < 0.2 and by < 0.1


def test_dim_scene_is_pulled_to_white():
    assert pull_dim_to_white(0.7, 0.3, 0.04, 0.04) == pytest.approx(WHITE_XY)
    assert pull_dim_to_white(0.7, 0.3, 0.5, 0.04) == (0.7, 0.3)
    x, _ = pull_dim_to_white(0.7, 0.3, 0.17, 0.04)
    assert WHITE_XY[0] < x < 0.7


def test_frame_targets_applies_scale():
    m = {"left": edge([px(255, 0, 0)] * 4), "right": edge([px(0, 0, 255)] * 4)}
    lights = [Light("a", "left"), Light("b", "all", scale=0.5)]
    out = frame_targets(m, lights, {}, 0.04)
    assert out["a"][2] == pytest.approx(1.0)
    assert out["b"][2] == pytest.approx(0.5)
