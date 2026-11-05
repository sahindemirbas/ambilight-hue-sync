"""Pure colour logic: edge sampling, dominant hue, RGB to CIE xy.

Nothing here talks to the network, so it is fully covered by tests.
"""
from __future__ import annotations

import colorsys

WHITE_XY = (0.3227, 0.329)
HUE_BINS = 12


def side_pixels(m: dict, side: str, a: float, b: float, top_first: dict) -> list[dict]:
    """Return the pixels of one TV edge between fractions a and b.

    The TV numbers pixels per edge as string keys ("0", "1", ...). Depending on
    the model one edge may be numbered from the top instead of the bottom;
    ``top_first`` flips that edge so 0.0 always means the bottom (or the left
    end of the top edge).
    """
    keys = sorted(m[side], key=int)
    if top_first.get(side):
        keys = keys[::-1]
    n = len(keys)
    lo = int(a * n)
    return [m[side][k] for k in keys[lo:max(lo + 1, round(b * n))]]


def dominant_rgb(px: list[dict]) -> list[float]:
    """Pick the strongest hue group and average only the pixels close to it.

    A plain average of orange and blue gives purple, a colour that is not on
    screen at all. Instead each pixel votes into a 12 bin hue histogram,
    weighted by value * saturation^2, the histogram is smoothed with its
    neighbours, and pixels within 45 degrees of the winning bin are averaged.
    Nearly grey scenes fall back to a plain average.
    """
    items, bins = [], [0.0] * HUE_BINS
    for p in px:
        r, g, b_ = p["r"], p["g"], p["b"]
        h, s_, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b_ / 255)
        w = vv * s_ * s_
        items.append((h, w, r, g, b_))
        bins[int(h * HUE_BINS) % HUE_BINS] += w
    if sum(bins) < 0.05:
        return [sum(p[k] for p in px) / len(px) for k in "rgb"]
    sm = [bins[i - 1] * 0.5 + bins[i] + bins[(i + 1) % HUE_BINS] * 0.5 for i in range(HUE_BINS)]
    hc = (sm.index(max(sm)) + 0.5) / HUE_BINS
    tot, acc = 0.0, [0.0, 0.0, 0.0]
    for h, w, r, g, b_ in items:
        d = min(abs(h - hc), 1 - abs(h - hc))
        if d <= 0.125:
            w += 0.02
            tot += w
            acc = [acc[0] + w * r, acc[1] + w * g, acc[2] + w * b_]
    return [c / tot for c in acc]


def region(m: dict, side: str, a: float, b: float, top_first: dict) -> tuple[list[float], float]:
    """Return (rgb, brightness 0..1) for a light's slice of the screen.

    ``side`` is "left", "right", "top" (or "bottom") or "all" for the whole
    frame. Brightness is the mean of max(r, g, b), so a saturated red counts
    as bright, which matches how the eye reads it.
    """
    if side == "all":
        px = [p for s in m.values() for p in s.values()]
    else:
        px = side_pixels(m, side, a, b, top_first)
    if not px:
        return [0, 0, 0], 0
    v = (sum(max(p["r"], p["g"], p["b"]) for p in px) / len(px)) / 255
    return dominant_rgb(px), v


def rgb_to_xy(rgb) -> tuple[float, float]:
    """sRGB (0..255) to CIE 1931 xy using the Hue wide gamut matrix."""
    def lin(c):
        c /= 255
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = (lin(c) for c in rgb)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    s = X + Y + Z
    return WHITE_XY if s == 0 else (X / s, Y / s)


def pull_dim_to_white(x: float, y: float, v: float, dark: float) -> tuple[float, float]:
    """In dim scenes hue is mostly noise, so blend the colour toward white.

    Full colour from brightness 0.30 upward, pure white at ``dark``.
    """
    if v < 0.30:
        k = max(0.0, (v - dark) / 0.26)
        x, y = WHITE_XY[0] + k * (x - WHITE_XY[0]), WHITE_XY[1] + k * (y - WHITE_XY[1])
    return x, y


def frame_targets(m: dict, lights: list, top_first: dict, dark: float) -> dict:
    """Turn one processed Ambilight frame into {name: (x, y, brightness)}."""
    out = {}
    for lt in lights:
        rgb, v = region(m, lt.side, lt.start, lt.end, top_first)
        x, y = rgb_to_xy(rgb)
        x, y = pull_dim_to_white(x, y, v, dark)
        out[lt.name] = (x, y, v * lt.scale)
    return out
