"""Hue Entertainment API v2 stream packet."""
from __future__ import annotations


def _u16(c: float) -> bytes:
    return int(max(0, min(1, c)) * 65535).to_bytes(2, "big")


def packet(seq: int, cfg_id: str, cur: dict, channels: dict) -> bytes:
    """Build one HueStream v2 packet in xy + brightness colour space.

    Header: "HueStream", version 2.0, sequence, 2 reserved, colour space
    (1 = xy), 1 reserved, then the 36 character entertainment configuration
    id. Each channel adds 7 bytes: channel id plus three 16 bit values.
    """
    h = b"HueStream" + bytes([2, 0, seq & 0xFF, 0, 0, 1, 0]) + cfg_id.encode()
    body = b""
    for name, (x, y, bri) in cur.items():
        body += bytes([channels[name]]) + _u16(x) + _u16(y) + _u16(bri)
    return h + body
