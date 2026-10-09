# SPDX-License-Identifier: GPL-3.0-or-later
"""Hillshaded contact sheet of every landform, without Blender.

    <blender python> tools/preview_shapes.py [--quality PREVIEW] [--out sheet.png] [--seed N] [SHAPE ...]

Runs with any Python that has numpy (Blender's bundled one works). Handy
while tuning recipes: no Blender, no rendering, a few seconds per shape.
"""

import os
import struct
import sys
import time
import types
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# load the bpy-free modules without running the add-on's __init__
pkg = types.ModuleType("summit")
pkg.__path__ = [os.path.join(ROOT, "summit")]
sys.modules["summit"] = pkg
from summit import generate, recipes  # noqa: E402


def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[h - 1 - y].tobytes() for y in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def shade(m, mode="shade"):
    if mode == "ao":
        return (np.repeat(m.ao[..., None], 3, -1) * 255).astype(np.uint8)
    nx, ny, nz = m.normal
    lx, ly, lz = -0.5, 0.5, 0.7
    ln = (lx * lx + ly * ly + lz * lz) ** 0.5
    lit = np.clip((nx * lx + ny * ly + nz * lz) / ln, 0, 1)
    h = m.h
    stops = ([.35, .45, .5, .95], [.45, .42, .45, .97], [.3, .33, .42, 1.0])
    ramp = np.stack([np.interp(h, [0, .35, .7, 1], c) for c in stops], -1)
    if mode == "flow":
        ramp = np.stack([m.flow, m.sediment, m.forest], -1)
        return (np.clip(ramp, 0, 1) * 255).astype(np.uint8)
    img = ramp * (0.25 + 0.85 * lit[..., None]) * (0.75 + 0.5 * (0.5 - m.cavity[..., None]) + 0.25)
    return (np.clip(img, 0, 1) ** (1 / 1.6) * 255).astype(np.uint8)


def main():
    argv = sys.argv[1:]
    q, out, seed, names, tile = "PREVIEW", os.path.join(ROOT, "preview_sheet.png"), 0, [], 320
    mode = "shade"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--quality", "--out", "--seed", "--tile", "--mode"):
            v = argv[i + 1]
            q, out, seed, tile, mode = (v if a == "--quality" else q, v if a == "--out" else out,
                                  int(v) if a == "--seed" else seed, int(v) if a == "--tile" else tile,
                                  v if a == "--mode" else mode)
            i += 2
        else:
            names.append(a.upper())
            i += 1
    ids = [s for s in recipes.SHAPES if not s.startswith("H_")] if not names else names
    tiles = []
    for sid in ids:
        t = time.time()
        ring = (3000.0, 2500.0) if sid.startswith("H_") else None
        m = generate.generate(sid, seed, q, 3000.0, 1100.0, ring=ring)
        img = shade(m, mode)
        if ring:
            img = img[:, : img.shape[0] * 3]
        ys = np.linspace(0, img.shape[0] - 1, tile if not ring else tile // 3).astype(int)
        xs = np.linspace(0, img.shape[1] - 1, tile).astype(int)
        tiles.append(img[ys][:, xs])
        print(f"{sid:16s} {time.time() - t:5.1f}s", flush=True)
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    th = max(t.shape[0] for t in tiles)
    sheet = np.zeros((rows * th, cols * tile, 3), np.uint8)
    for k, t in enumerate(tiles):
        r, cidx = divmod(k, cols)
        r = rows - 1 - r
        sheet[r * th: r * th + t.shape[0], cidx * tile:(cidx + 1) * tile] = t
    write_png(out, sheet)
    print("wrote", out)


main()
