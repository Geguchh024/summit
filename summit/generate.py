# SPDX-License-Identifier: GPL-3.0-or-later
"""From a recipe to finished maps: shape, erosion, fine detail, normals and masks.

The landform is simulated at a modest resolution (erosion is the slow
part), then upsampled smoothly to the texture resolution, where fine rock
detail is added. The mesh only has to carry the silhouette: the normal map
carries the detail. This module does not use bpy.
"""

from dataclasses import dataclass

import numpy as np

from . import field
from .recipes import SHAPES, Ctx

# simulation cells, texture pixels, mesh vertices (per side for terrains)
QUALITY = {
    "PREVIEW": (192, 512, 128),
    "MEDIUM": (320, 1024, 256),
    "HIGH": (512, 2048, 512),
    "ULTRA": (768, 4096, 1024),
}


@dataclass
class Maps:
    h: np.ndarray           # height 0..1 at texture resolution
    normal: tuple           # (x, y, z) unit normal arrays in the field's own frame
    flow: np.ndarray        # 0..1, bright along water channels
    sediment: np.ndarray    # 0..1, where eroded material and scree settled
    cavity: np.ndarray      # 0..1, 0.5 flat, high in gullies, low on ridges
    forest: np.ndarray      # 0..1, how well trees would grow (ignores altitude)
    ao: np.ndarray          # 0..1, sky visibility (1 open, 0 enclosed)
    wrap: bool
    cell: tuple             # (x, y) texture cell size in metres


def grid_shape(quality, ring=None):
    """((sim rows, cols), (map rows, cols)) for a terrain, or for a ring (inner radius, depth)."""
    sim, tex, _mesh = QUALITY[quality]
    if ring is None:
        return (sim, sim), (tex, tex)
    aspect = ring_aspect(*ring)
    rs = max(48, sim // 3)
    rt = max(128, tex // 6)
    return (rs, int(round(rs * aspect))), (rt, int(round(rt * aspect)))


def ring_aspect(radius, depth):
    """Ring circumference (at its middle) over its depth: the x extent of its coordinates."""
    return 2.0 * np.pi * (radius + depth * 0.5) / depth


def generate(shape_id, seed=0, quality="MEDIUM", size=2000.0, height=800.0, erosion=1.0, falloff=0.0,
             ring=None, progress=None):
    """Build all maps for one terrain.

    size: terrain width in metres (ignored for rings). ring: (inner radius,
    depth) in metres to build a seamless horizon band instead.
    """
    report = progress or (lambda f, label="": None)
    shape = SHAPES[shape_id]
    (sy, sx), (ty, tx) = grid_shape(quality, ring)
    wrap = ring_aspect(*ring) if ring else None
    if ring:
        cell_sim = ((2.0 * np.pi * (ring[0] + ring[1] * 0.5)) / sx, ring[1] / sy)
        # arc length per texel grows with the radius: one value per row
        radii = ring[0] + (np.arange(ty)[:, None] + 0.5) / ty * ring[1]
        cell_tex = (2.0 * np.pi * radii / tx, ring[1] / ty)
    else:
        cell_sim = (size / sx, size / sy)
        cell_tex = (size / tx, size / ty)

    report(0.02, "Shaping")
    c = Ctx(sy, sx, seed, wrap)
    h = field.normalize(shape.fn(c))
    if falloff > 0.0 and not ring:
        edge = np.minimum(np.minimum(c.X, 1.0 - c.X), np.minimum(c.Y, 1.0 - c.Y)) * 2.0
        edge = edge + 0.08 * falloff * c.fbm(3.0, 3, salt=91)
        h = h * field.smoothstep(0.0, falloff, edge)

    # erosion works in cell units, so a slope of 1 is 45 degrees whatever the size
    cs = (cell_sim[0] + cell_sim[1]) * 0.5
    hc = h * height / cs
    flow = np.zeros_like(hc)
    dep = np.zeros_like(hc)
    drops = int(sx * sy * shape.erosion * erosion)
    if drops > 0:
        rng = np.random.default_rng(seed + 7)
        hc, flow, dep = field.erode_hydraulic(hc, drops, rng, wrap_x=bool(wrap),
                                              progress=lambda f: report(0.05 + 0.6 * f, "Eroding"))
    report(0.66, "Settling scree")
    if shape.thermal:
        hc, gained = field.erode_thermal(hc, np.tan(np.radians(shape.talus)), shape.thermal, wrap_x=bool(wrap))
        dep = dep + gained
    h = hc * cs / height
    if shape.post:
        h = shape.post(c, field.normalize(h))
    h = field.normalize(h)
    flow = field.flow_mask(flow, bool(wrap)) if drops else np.zeros_like(h)
    # only real fans and aprons count as sediment, not the thin film deposited everywhere
    sed = np.log1p(dep * 4.0)
    lo, hi = np.percentile(sed, 65.0), np.percentile(sed, 99.5) + 1e-9
    sed = np.clip((sed - lo) / max(hi - lo, 1e-9), 0.0, 1.0) ** 1.5

    report(0.72, "Adding detail")
    up = lambda a: field.resample(a, ty, tx, bool(wrap)).astype(np.float32)  # noqa: E731
    H = up(h)
    flow, sed = np.clip(up(flow), 0, 1), np.clip(up(sed), 0, 1)
    ct = Ctx(ty, tx, seed + 1, wrap)
    if shape.detail > 0.0:
        # branching gullies below the simulation scale, on rock but not on scree (finer octaves read as fur)
        hm = H * height
        lam = 6.0 * (tx / sx if not wrap else ty / sy)
        hm = field.gully_detail(hm, cell_tex[0], lam, 2, 0.12 * shape.detail, seed, bool(wrap),
                                mask=1.0 - 0.7 * sed)
        rough = field.slope(hm, *cell_tex, bool(wrap))
        rock = field.smoothstep(0.35, 1.2, rough)
        grain = (ct.ridged((sx if not wrap else sy) / 1.5, 3, salt=77) - 0.45) * cs * 0.25 * shape.detail
        H = np.clip((hm + grain * rock) / height, 0.0, None).astype(np.float32)

    report(0.85, "Baking maps")
    hm = H * height
    nrm = field.normal_map(hm, *cell_tex, bool(wrap))
    # trees care about the broad slope, not rock detail: judge it on a softened field
    soft = field.blur(hm, max(2.0, tx / 256.0), bool(wrap))
    slope = field.slope(soft, *cell_tex, bool(wrap))
    cav = field.cavity(hm, float(np.mean(cell_tex[0]) + cell_tex[1]) * 0.5, bool(wrap))
    clumps = field.smoothstep(-0.25, 0.35, ct.fbm(7.0 if not wrap else 2.5, 4, salt=55))
    # meadows and clearings: real forests are never one even carpet
    open_ground = field.smoothstep(-0.18, 0.12, ct.fbm(3.5 if not wrap else 1.2, 5, salt=57))
    forest = (field.smoothstep(0.85, 0.3, slope) * (1.0 - 0.75 * field.smoothstep(0.55, 0.95, flow))
              * (1.0 - 0.6 * field.smoothstep(0.5, 1.0, sed)) * (0.35 + 0.65 * clumps) * open_ground)
    report(0.9, "Baking occlusion")
    k = max(1, ty // 2048)
    if k > 1:   # occlusion is soft: half resolution is plenty and four times faster
        ao = field.horizon_ao(field.resample(hm, ty // k, tx // k, bool(wrap)), np.mean(cell_tex[0]) * k, bool(wrap))
        ao = np.clip(field.resample(ao, ty, tx, bool(wrap)), 0.0, 1.0)
    else:
        ao = field.horizon_ao(hm, cell_tex[0], bool(wrap))
    report(0.95, "Building mesh")
    return Maps(H.astype(np.float32), tuple(n.astype(np.float32) for n in nrm), flow.astype(np.float32),
                sed.astype(np.float32), cav.astype(np.float32), forest.astype(np.float32), ao.astype(np.float32),
                bool(wrap), cell_tex)


# -- surroundings -------------------------------------------------------------

def perimeter(res):
    """Indices of a res x res grid's border vertices, counter-clockwise from the (0, 0) corner."""
    i = np.arange(res - 1)
    return np.concatenate([i, (i * res + res - 1), (res - 1) * res + res - 1 - i, (res - 1 - i) * res])


def apron_loops(res):
    """Number of vertex loops between a terrain's border and the edge of its surroundings."""
    return max(12, int(res ** 0.625))


def apron(edge_xy, edge_z, size, height, seed=0, water=-1.0, reach=1.5, loops=24):
    """Surroundings for a square terrain: loops of vertices from its border out to a circle.

    The terrain's edge flows down into low rolling ground that rises again
    into a rim of hills, so a camera inside the scene never sees the end of
    the world. edge_xy: (P, 2) border positions in metres around the centre,
    counter-clockwise; edge_z: (P,) their heights. reach: outer radius in
    terrain widths. Returns positions (loops, P, 3), a forest mask and the
    blend from terrain to surroundings (both (loops, P), 0..1).
    """
    from .noise import Noise
    n = Noise(seed + 404)
    p = len(edge_z)
    r0 = np.hypot(edge_xy[:, 0], edge_xy[:, 1])
    direction = edge_xy / np.maximum(r0, 1e-6)[:, None]
    outer = reach * size
    t = (np.arange(1, loops + 1) / loops) ** 1.6
    d = t[:, None] * (outer - r0)[None, :]                     # distance from the terrain's border
    xy = edge_xy[None] + direction[None] * d[..., None]
    X = xy[..., 0] / size + 0.5
    Y = xy[..., 1] / size + 0.5
    # carry on at the terrain's usual edge level: a plateau stays a plateau, a valley floor stays low
    lo = float(np.percentile(edge_z, 40.0)) / height
    lo = max(lo - 0.04, water - 0.04) if water > -0.5 else max(lo - 0.04, 0.015)
    rolling = 0.5 + 0.5 * n.fbm(X, Y, 1.3, 5, salt=3)
    foothills = n.ridged(X, Y, 2.4, 7, salt=13) * field.smoothstep(0.0, 0.3, d / (outer - r0)[None, :])
    rim = n.ridged(X, Y, 0.8, 6, salt=9) * field.smoothstep(0.25, 0.95, d / (outer - r0)[None, :])
    relief = max(1.0 - lo, 0.2)
    target = height * (lo + relief * (0.08 * rolling + 0.16 * foothills + 0.5 * rim))
    # high edges need room to come down at a believable slope
    ez = edge_z.astype(np.float64)
    for _ in range(3):
        ez = np.maximum(ez, 0.5 * (np.roll(ez, 1) + np.roll(ez, -1)))
    reach_down = np.maximum(0.12 * size, 2.2 * np.maximum(ez - target[0], 0.0))
    s = field.smoothstep(0.0, 1.0, d / reach_down[None, :])
    z = edge_z[None, :] * (1.0 - s) + target * s
    # spurs and gullies on the way down, fading out on the plain
    z += height * 0.05 * n.ridged(X, Y, 6.0, 5, salt=21) * field.smoothstep(0.0, 0.08 * size, d) * (1.0 - 0.6 * s)
    co = np.concatenate([xy, z[..., None]], -1)

    gz0, gz1 = np.gradient(z)
    dr = np.gradient(d, axis=0)
    dt = np.hypot(*np.gradient(xy, axis=1).transpose(2, 0, 1))
    slope = np.hypot(gz0 / np.maximum(dr, 1e-3), gz1 / np.maximum(dt, 1e-3))
    clumps = field.smoothstep(-0.25, 0.35, n.fbm(X, Y, 7.0, 4, salt=55))
    open_ground = field.smoothstep(-0.18, 0.12, n.fbm(X, Y, 3.5, 5, salt=57))
    forest = field.smoothstep(0.85, 0.3, slope) * (0.35 + 0.65 * clumps) * open_ground
    # trees near the terrain only: farther out the shader's forest tint carries it, for free
    forest *= 1.0 - field.smoothstep(0.25, 0.55, d / (outer - r0)[None, :])
    blend = field.smoothstep(0.0, 3.0 * size / max(p / 4.0, 1.0), d)
    return co.astype(np.float32), forest.astype(np.float32), blend.astype(np.float32)
