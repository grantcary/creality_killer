"""G-code -> extrusion toolpath, for preview.

Only extruding moves are kept. Every segment records the byte offset of its
source line so live progress (Klipper's virtual_sdcard.file_position) maps
straight to a segment/layer without any line counting.
"""
from __future__ import annotations

import math
import re
from array import array
from dataclasses import dataclass

import numpy as np

_WORD = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
ARC_CHORD_MM = 0.75


@dataclass
class Toolpath:
    segments: np.ndarray  # (N, 6) float32: x0 y0 z0 x1 y1 z1
    layer: np.ndarray  # (N,) int32
    kind: np.ndarray  # (N,) uint8, index into `kinds`
    offset: np.ndarray  # (N,) int64 byte offset of the source line
    kinds: list[str]
    layer_z: list[float]
    layer_start: np.ndarray  # (L+1,) first segment of each layer, last = N

    @property
    def n_layers(self) -> int:
        return len(self.layer_z)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        pts = self.segments.reshape(-1, 3)
        return pts.min(axis=0), pts.max(axis=0)

    def segment_at_offset(self, file_position: int) -> int:
        """Index of the last segment at or before `file_position` (-1 if none)."""
        return int(np.searchsorted(self.offset, file_position, side="right")) - 1

    def layer_at_offset(self, file_position: int) -> int:
        i = self.segment_at_offset(file_position)
        return int(self.layer[i]) if i >= 0 else 0


def _feature_name(comment: str) -> str | None:
    c = comment.strip()
    if c.upper().startswith("TYPE:"):
        return c[5:].strip() or None
    if c.upper().startswith("FEATURE:"):  # Orca/Bambu style
        return c[8:].strip() or None
    return None


def parse_gcode(data: bytes | str) -> Toolpath:
    # latin-1 maps bytes 1:1 to chars, so char index == byte offset
    text = data.decode("latin-1") if isinstance(data, bytes) else data
    marker_layers = ";LAYER_CHANGE" in text or "\n;LAYER:" in text

    xyz = array("f")
    layers, kinds_idx = array("i"), array("B")
    offsets = array("q")
    kinds: list[str] = []
    kind_ids: dict[str, int] = {}

    def kind_id(name: str) -> int:
        if name not in kind_ids:
            kind_ids[name] = len(kinds)
            kinds.append(name)
        return kind_ids[name]

    cur_kind = kind_id("Unknown")
    x = y = z = e = 0.0
    abs_xyz = abs_e = True
    layer = -1
    layer_z: list[float] = []
    pending_layer = False
    cur_layer_z = None
    pos = 0

    def emit(x0, y0, z0, x1, y1, z1, off):
        nonlocal layer, pending_layer, cur_layer_z
        if marker_layers:
            if pending_layer or layer < 0:
                layer += 1
                layer_z.append(z1)
                pending_layer = False
        elif cur_layer_z is None or abs(z1 - cur_layer_z) > 1e-3:
            layer += 1
            layer_z.append(z1)
            cur_layer_z = z1
        xyz.extend((x0, y0, z0, x1, y1, z1))
        layers.append(layer)
        kinds_idx.append(cur_kind)
        offsets.append(off)

    for line in text.split("\n"):
        line_off = pos
        pos += len(line) + 1
        code, _, comment = line.partition(";")
        if comment:
            name = _feature_name(comment)
            if name:
                cur_kind = kind_id(name)
            elif marker_layers and (comment.startswith("LAYER_CHANGE") or comment.startswith("LAYER:")):
                pending_layer = True
        code = code.strip()
        if not code:
            continue
        cmd = code.split(None, 1)[0].upper()

        if cmd in ("G0", "G1", "G2", "G3"):
            w = {k.upper(): float(v) for k, v in _WORD.findall(code[len(cmd):])}
            nx = (x + w["X"] if not abs_xyz else w["X"]) if "X" in w else x
            ny = (y + w["Y"] if not abs_xyz else w["Y"]) if "Y" in w else y
            nz = (z + w["Z"] if not abs_xyz else w["Z"]) if "Z" in w else z
            extruding = False
            if "E" in w:
                ne = e + w["E"] if not abs_e else w["E"]
                extruding = ne > e + 1e-9
                e = ne
            if extruding and (nx != x or ny != y or nz != z):
                if cmd in ("G2", "G3") and ("I" in w or "J" in w):
                    _arc(cmd == "G2", x, y, z, nx, ny, nz, w.get("I", 0.0), w.get("J", 0.0),
                         lambda *a: emit(*a, line_off))
                else:
                    emit(x, y, z, nx, ny, nz, line_off)
            x, y, z = nx, ny, nz
        elif cmd == "G90":
            abs_xyz = True  # Klipper: E mode is set only by M82/M83
        elif cmd == "G91":
            abs_xyz = False
        elif cmd == "M82":
            abs_e = True
        elif cmd == "M83":
            abs_e = False
        elif cmd == "G92":
            w = {k.upper(): float(v) for k, v in _WORD.findall(code[3:])}
            if "E" in w:
                e = w["E"]
            x, y, z = w.get("X", x), w.get("Y", y), w.get("Z", z)

    n = len(layers)
    seg = np.frombuffer(xyz, dtype=np.float32).reshape(n, 6).copy() if n else np.zeros((0, 6), np.float32)
    lay = np.frombuffer(layers, dtype=np.int32).copy() if n else np.zeros(0, np.int32)
    n_layers = len(layer_z)
    starts = np.searchsorted(lay, np.arange(n_layers + 1)) if n else np.zeros(1, np.int64)
    return Toolpath(
        segments=seg,
        layer=lay,
        kind=np.frombuffer(kinds_idx, dtype=np.uint8).copy() if n else np.zeros(0, np.uint8),
        offset=np.frombuffer(offsets, dtype=np.int64).copy() if n else np.zeros(0, np.int64),
        kinds=kinds,
        layer_z=layer_z,
        layer_start=starts,
    )


def _arc(cw, x0, y0, z0, x1, y1, z1, i, j, out) -> None:
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    if r < 1e-9:
        out(x0, y0, z0, x1, y1, z1)
        return
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw and sweep >= 0:
        sweep -= 2 * math.pi
    elif not cw and sweep <= 0:
        sweep += 2 * math.pi
    steps = max(1, int(abs(sweep) * r / ARC_CHORD_MM))
    px, py, pz = x0, y0, z0
    for s in range(1, steps + 1):
        t = s / steps
        a = a0 + sweep * t
        nx, ny, nz = (x1, y1, z1) if s == steps else (cx + r * math.cos(a), cy + r * math.sin(a), z0 + (z1 - z0) * t)
        out(px, py, pz, nx, ny, nz)
        px, py, pz = nx, ny, nz
