"""Exponential smoothing between the slow TV samples and the fast stream."""
from __future__ import annotations

import math


def smooth_step(cur, tgt, dt: float, consts, dark: float):
    """Move one light's (x, y, brightness) a step toward the target.

    ``consts`` is (rise, fall, colour) time constants in seconds. Brightening
    and dimming use separate constants so flashes feel quick while fades out
    stay soft. Brightness below ``dark`` is forced to 0 so the light really
    turns off. When the light is currently near black, colour jumps straight
    to the target instead of fading in from white.
    """
    ox, oy, ov = cur
    x, y, v = tgt
    tr, tf, tc = consts
    kv = 1 - math.exp(-dt / (tr if v >= ov else tf))
    kc = 1 - math.exp(-dt / tc)
    if v < dark:
        v = 0.0
    if ov < 0.02:
        kc = 1.0
    return (ox + kc * (x - ox), oy + kc * (y - oy), ov + kv * (v - ov))
