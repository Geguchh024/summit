# SPDX-License-Identifier: GPL-3.0-or-later
"""Landform recipes: each builds the raw shape of one kind of terrain before erosion.

A recipe gets a ``Ctx`` (coordinate grids plus seeded noise) and returns a
height array in roughly 0..1. Coordinates run 0..1 across a terrain. For
the horizon ring x runs 0..wrap around the ring and y runs 0..1 from the
inner edge outward, and all noise tiles in x. This module does not use bpy.
"""

from dataclasses import dataclass

import numpy as np

from .field import apron as field_apron
from .field import blur, normalize, smoothstep, terrace
from .noise import Noise

TAU = 2.0 * np.pi


class Ctx:
    def __init__(self, ny, nx, seed, wrap=None):
        if wrap:
            xs = np.arange(nx) / nx * wrap
        else:
            xs = (np.arange(nx) + 0.5) / nx
        ys = (np.arange(ny) + 0.5) / ny
        self.X, self.Y = np.meshgrid(xs, ys)
        self.wrap = wrap
        self.noise = Noise(seed)
        self.rng = np.random.default_rng(seed)
        self.cells = max(nx, ny) if not wrap else ny

    def _xy(self, x, y):
        return (self.X if x is None else x), (self.Y if y is None else y)

    def fbm(self, freq, octaves=6, x=None, y=None, **kw):
        x, y = self._xy(x, y)
        return self.noise.fbm(x, y, freq, octaves, wrap=self.wrap, **kw)

    def ridged(self, freq, octaves=8, x=None, y=None, **kw):
        x, y = self._xy(x, y)
        return self.noise.ridged(x, y, freq, octaves, wrap=self.wrap, **kw)

    def voronoi(self, freq, x=None, y=None, **kw):
        x, y = self._xy(x, y)
        return self.noise.voronoi(x, y, freq, wrap=self.wrap, **kw)

    def warp(self, amount, freq, octaves=4, salt=500, x=None, y=None):
        """Domain-warped coordinates: bends straight features into natural curves."""
        x, y = self._xy(x, y)
        wx = self.noise.fbm(x, y, freq, octaves, wrap=self.wrap, salt=salt)
        wy = self.noise.fbm(x, y, freq, octaves, wrap=self.wrap, salt=salt + 17)
        return x + amount * wx, y + amount * wy

    def line(self, freq, octaves=3, salt=0, x=None):
        """1D noise along x, for meandering rivers and spines."""
        x = self.X if x is None else x
        return self.noise.fbm(x, np.full_like(x, 0.37 + salt * 1.7), freq, octaves, wrap=self.wrap, salt=salt)

    def blur(self, a, radius_frac):
        return blur(a, radius_frac * self.cells, bool(self.wrap))


def _dist(x, y, cx=0.5, cy=0.5):
    return np.hypot(x - cx, y - cy)


# -- mountains --------------------------------------------------------------

def _smin(a, b, k):
    """Smooth minimum: like np.minimum, with the crease rounded over k."""
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def _ridge(x, y, pts, crest, slope):
    """Height of a sharp ridge along a polyline: crest heights at the points, faces falling at slope."""
    out = np.full(x.shape, -9.0)
    for (px, py), (qx, qy), hp, hq in zip(pts[:-1], pts[1:], crest[:-1], crest[1:]):
        ex, ey = qx - px, qy - py
        t = np.clip(((x - px) * ex + (y - py) * ey) / max(ex * ex + ey * ey, 1e-9), 0.0, 1.0)
        d = np.hypot(x - px - t * ex, y - py - t * ey)
        out = np.maximum(out, hp + t * (hq - hp) - slope * d)
    return out


def alpine_peak(c):
    """A summit with three or four arêtes, side spurs, cirques between them and a skirt of foothills."""
    rng = c.rng
    x, y = c.warp(0.025, 2.2)
    sx, sy = 0.5 + rng.uniform(-0.05, 0.05), 0.5 + rng.uniform(-0.05, 0.05)
    n = int(rng.integers(3, 5))
    base = rng.uniform(0.0, TAU)
    angles = base + np.arange(n) * TAU / n + rng.uniform(-0.35, 0.35, n)
    h = np.full(x.shape, -9.0)
    for i, a0 in enumerate(angles):
        length = rng.uniform(0.34, 0.5)
        k = 14
        t = np.linspace(0.0, 1.0, k)
        bend = np.cumsum(rng.normal(0.0, 0.18, k)) * 0.35
        ang = a0 + bend * t
        r = t * length
        pts = list(zip(sx + r * np.cos(ang), sy + r * np.sin(ang)))
        # the crest drops fast below the summit, then steps down over lesser tops
        top = rng.uniform(0.82, 1.0) if i else 1.0     # one main summit, lesser tops on the other arêtes
        notches = 0.07 * np.sin(t * rng.uniform(9.0, 14.0) + rng.uniform(0, TAU)) + rng.normal(0.0, 0.035, k)
        crest = top - 0.8 * top * t ** 0.65 + notches * np.sin(np.pi * t)
        h = np.maximum(h, _ridge(x, y, pts, crest, 2.4))
        # a side spur or two branching off the arête
        for _ in range(int(rng.integers(1, 3))):
            j = int(rng.integers(4, 9))
            side = ang[j] + rng.choice([-1.0, 1.0]) * rng.uniform(0.7, 1.2)
            ln = rng.uniform(0.12, 0.2)
            tt = np.linspace(0.0, 1.0, 6)
            sa = side + np.cumsum(rng.normal(0.0, 0.2, 6)) * 0.3
            spts = list(zip(pts[j][0] + tt * ln * np.cos(sa), pts[j][1] + tt * ln * np.sin(sa)))
            h = np.maximum(h, _ridge(x, y, spts, crest[j] * (1.0 - 0.7 * tt ** 0.8), 2.4))
    # cirques: bowls scooped out of the faces between neighbouring arêtes, holding snowfields
    order = np.sort(np.mod(angles, TAU))
    for a1, a2 in zip(order, np.roll(order, -1)):
        mid = a1 + np.mod(a2 - a1, TAU) * 0.5
        rc = rng.uniform(0.15, 0.22)
        cx, cy = sx + rc * np.cos(mid), sy + rc * np.sin(mid)
        floor = 0.4 + rng.uniform(-0.06, 0.06)
        d = np.hypot(x - cx, y - cy)
        h = _smin(h, floor + 40.0 * d * d, 0.04)
    # concave, like real mountains: steep near the top, easing into grassy lower slopes
    h = np.maximum(h, 0.0) ** 1.5
    d = _dist(x, y, sx, sy)
    rough = c.ridged(3.0, 9, x=x, y=y)
    skirt = np.clip(1.0 - d / 0.75, 0.0, 1.0)
    foothills = c.ridged(2.2, 7, x=x, y=y, salt=13)
    return h + 0.11 * rough * smoothstep(0.05, 0.6, h) + skirt * (0.1 + 0.16 * foothills)


def mountain_range(c):
    x, y = c.warp(0.07, 1.3)
    spine = 0.5 + 0.13 * c.line(1.1, x=x) + 0.04 * np.sin(x * TAU * 0.8)
    band = np.exp(-((y - spine) / 0.26) ** 2)
    far = np.exp(-((y - spine - 0.33) / 0.16) ** 2) * 0.5 + np.exp(-((y - spine + 0.34) / 0.15) ** 2) * 0.4
    r = c.ridged(2.8, 9, x=x, y=y)
    peaks = c.ridged(1.4, 4, x=x, y=y, salt=23)
    mass = band + far
    return mass * (0.15 + 0.85 * r ** 1.3) * (0.6 + 0.6 * peaks) + 0.1 * r


def snowy_massif(c):
    x, y = c.warp(0.08, 1.1)
    d = _dist(x, y)
    dome = np.clip(1.0 - (d / 0.58) ** 2, 0.0, 1.0)
    lumps = 0.5 + 0.5 * c.fbm(2.0, 5, x=x, y=y, billow=True)
    r = c.ridged(2.0, 8, x=x, y=y, salt=11)
    h = dome ** 0.9 * (0.4 + 0.35 * lumps + 0.45 * r)
    # flatten the top into broad snowfields
    return np.minimum(h, 0.8 + 0.15 * h)


def volcano(c):
    x, y = c.warp(0.025, 2.0)
    d = _dist(x, y)
    th = np.arctan2(y - 0.5, x - 0.5)
    prof = np.clip(1.0 - d / 0.56, 0.0, 1.0) ** 2.1
    # radial gullies down the flanks: ridged noise in polar coordinates
    u = (th / TAU + 0.5) * 18.0
    gully = c.noise.ridged(u, d * 9.0, 1.0, 5, wrap=18.0, salt=33)
    rim = np.exp(-((d - 0.085) / 0.03) ** 2) * 0.07
    bowl = smoothstep(0.095, 0.035, d) * 0.3
    hills = 0.5 + 0.5 * c.fbm(3.0, 6, salt=3)
    return prof * 0.95 + rim - bowl + gully * prof * 0.07 + 0.06 * hills * (1.0 - prof)


def dolomites(c):
    x, y = c.warp(0.04, 2.5)
    f1, f2, cid = c.voronoi(5.0, x=x, y=y, jitter=0.85)
    edge = f2 - f1
    tower = smoothstep(0.1, 0.16, edge + 0.05 * c.fbm(12.0, 3, salt=5))
    massif = smoothstep(-0.3, 0.25, c.fbm(1.3, 4, salt=8))
    heights = (0.3 + 0.7 * cid ** 1.2) * massif
    jag = c.ridged(10.0, 5, x=x, y=y, salt=21)
    base = 0.15 * (0.5 + 0.5 * c.fbm(2.0, 5, salt=4)) + 0.1 * massif
    h = tower * heights * (0.8 + 0.3 * jag) + base
    return terrace(np.clip(h, 0.0, 1.2) / 1.2, 8, 0.6, 0.2 * c.fbm(3.0, 3, salt=9))


def _dolomite_post(c, h):
    # scree aprons at the foot of the walls, then a little fresh breakage
    return field_apron(h, 0.025 * c.cells, 0.03, bool(c.wrap))


# -- hills ------------------------------------------------------------------

def rolling_hills(c):
    x, y = c.warp(0.1, 0.9)
    a = c.fbm(1.8, 6, x=x, y=y, gain=0.42)
    b = c.fbm(3.5, 4, x=x, y=y, billow=True, salt=5)
    h = 0.5 + 0.5 * (0.8 * a + 0.2 * b)
    return h ** 1.25


def highlands(c):
    x, y = c.warp(0.08, 1.2)
    r = c.ridged(2.2, 8, x=x, y=y)
    f = 0.5 + 0.5 * c.fbm(1.3, 5, salt=6)
    h = 0.55 * r + 0.45 * f
    return normalize(h) ** 1.7


def foothills(c):
    x, y = c.warp(0.07, 1.5)
    r = c.ridged(3.2, 8, x=x, y=y)
    f = 0.5 + 0.5 * c.fbm(1.1, 4, salt=2)
    return r * (0.45 + 0.55 * f) + 0.25 * f


# -- canyons and desert -----------------------------------------------------

def canyon(c):
    x, y = c.warp(0.035, 1.8)
    yc = 0.5 + 0.17 * np.sin(x * TAU * 1.15 + 0.6) + 0.07 * c.line(2.0, x=x, salt=3)
    dd = np.abs(y - yc)
    main = smoothstep(0.025, 0.2, dd + 0.04 * c.fbm(5.0, 4, salt=4))
    gul = np.abs(c.fbm(3.2, 5, x=x, y=y, salt=12))
    side = smoothstep(0.015, 0.12, gul)
    near = smoothstep(0.42, 0.12, dd)
    h = np.minimum(main, 1.0 - near * (1.0 - side))
    h = terrace(h, 6, 0.85, 0.18 * c.fbm(2.0, 3, salt=14))
    return 0.12 + 0.82 * h + 0.025 * c.fbm(8.0, 4, salt=15) * h


def mesas(c):
    x, y = c.warp(0.05, 2.0)
    m = c.fbm(2.0, 6, x=x, y=y)
    top = smoothstep(0.06, 0.1, m)
    tier = smoothstep(0.3, 0.33, m) * 0.35
    butte = smoothstep(0.42, 0.45, m) * 0.25
    floor = 0.05 * (0.5 + 0.5 * c.fbm(4.0, 5, salt=6))
    return floor + 0.55 * top + tier + butte


def dunes(c):
    a = 0.35
    x, y = c.warp(0.04, 1.5)
    u = x * np.cos(a) + y * np.sin(a)
    v = -x * np.sin(a) + y * np.cos(a)
    s = u * 7.0 + 0.6 * c.fbm(2.2, 4, x=u, y=v * 0.6, salt=3) + 0.25 * c.fbm(5.0, 3, salt=8)
    s = s - np.floor(s)
    prof = np.where(s < 0.78, s / 0.78, (1.0 - s) / 0.22)
    prof = smoothstep(0.0, 1.0, prof)
    amp = 0.55 + 0.45 * smoothstep(-0.4, 0.4, c.fbm(1.6, 4, salt=11))
    return prof * amp * 0.6 + 0.4 * (0.5 + 0.5 * c.fbm(1.2, 4, salt=2))


def badlands(c):
    x, y = c.warp(0.06, 2.0)
    f = 0.5 + 0.5 * c.fbm(2.2, 6, x=x, y=y)
    r = c.ridged(5.0, 6, x=x, y=y, salt=4)
    h = 0.55 * f + 0.45 * r * f
    return terrace(normalize(h), 11, 0.35, 0.1 * c.fbm(4.0, 3, salt=7))


# -- landscapes -------------------------------------------------------------

def valley(c):
    x, y = c.warp(0.05, 1.2)
    yc = 0.5 + 0.08 * np.sin(x * TAU * 0.7 + 1.0) + 0.04 * c.line(1.8, x=x, salt=5)
    dd = np.abs(y - yc)
    u = smoothstep(0.05, 0.42, dd) ** 1.5
    r = c.ridged(2.8, 9, x=x, y=y)
    floor = 0.02 * c.fbm(4.0, 4, salt=6)
    return u * (0.35 + 0.65 * r) + 0.35 * u ** 3 + floor


def vast(c):
    x, y = c.warp(0.07, 1.0)
    macro = c.fbm(0.9, 4, x=x, y=y, salt=1)
    mtn = smoothstep(-0.05, 0.45, macro)
    r = c.ridged(3.2, 9, x=x, y=y)
    hills = 0.5 + 0.5 * c.fbm(3.0, 6, salt=2)
    h = mtn * (0.2 + 0.8 * r) + 0.18 * hills + 0.1 * mtn ** 2
    river = np.abs(c.fbm(1.3, 5, x=x, y=y, salt=9))
    carve = smoothstep(0.0, 0.07, river)
    return h * (0.55 + 0.45 * carve)


def fjord(c):
    x, y = c.warp(0.05, 1.4)
    r = c.ridged(2.6, 9, x=x, y=y)
    inlet = np.abs(c.fbm(1.3, 4, x=x, y=y, salt=19))
    walls = smoothstep(0.02, 0.16, inlet)
    return (0.3 + 0.7 * r) * walls * (0.6 + 0.4 * walls) - 0.12 * (1.0 - walls)


def karst(c):
    x, y = c.warp(0.04, 3.0)
    f1, _f2, cid = c.voronoi(9.0, x=x, y=y, jitter=0.95)
    tower = smoothstep(0.42, 0.12, f1 * (1.15 - 0.3 * cid))
    clusters = smoothstep(-0.2, 0.25, c.fbm(1.8, 4, salt=6))
    h = tower ** 0.55 * (0.4 + 0.6 * cid) * clusters
    plain = 0.03 * (0.5 + 0.5 * c.fbm(5.0, 4, salt=2))
    return h + plain


def archipelago(c):
    x, y = c.warp(0.06, 1.5)
    d = _dist(x, y)
    f = c.fbm(2.4, 7, x=x, y=y)
    r = c.ridged(4.0, 6, x=x, y=y, salt=5)
    land = f + 0.35 - 0.9 * d ** 1.5
    return land + 0.25 * r * smoothstep(0.0, 0.3, land)


# -- horizon ring -----------------------------------------------------------

def _envelope(c):
    """Rises from the inner edge of the ring, so the foot of the range sits on the ground."""
    return smoothstep(0.0, 0.45, c.Y) * (1.0 - 0.6 * smoothstep(0.85, 1.0, c.Y))


def horizon_peaks(c):
    x, y = c.warp(0.05, 1.2)
    r = c.ridged(1.4, 9, x=x, y=y)
    big = 0.5 + 0.5 * c.fbm(0.35, 3, salt=4)
    return _envelope(c) * (0.2 + 0.8 * r) * (0.45 + 0.55 * big) + 0.15 * smoothstep(0.4, 1.0, c.Y) * r


def horizon_hills(c):
    x, y = c.warp(0.08, 0.8)
    f = 0.5 + 0.5 * c.fbm(1.0, 6, x=x, y=y, gain=0.45)
    return _envelope(c) * f ** 1.3


def horizon_mesas(c):
    x, y = c.warp(0.05, 1.0)
    m = c.fbm(1.2, 6, x=x, y=y)
    top = smoothstep(0.05, 0.09, m) * 0.7 + smoothstep(0.32, 0.35, m) * 0.3
    return _envelope(c) ** 0.6 * (0.08 + top)


def horizon_snow(c):
    x, y = c.warp(0.06, 1.0)
    r = c.ridged(1.1, 9, x=x, y=y, salt=3)
    lumps = 0.5 + 0.5 * c.fbm(1.0, 5, x=x, y=y, billow=True)
    return _envelope(c) * (0.35 + 0.45 * r + 0.25 * lumps)


@dataclass
class Shape:
    fn: object
    erosion: float = 1.0        # droplets per cell
    talus: float = 40.0         # degrees; steeper slopes shed scree
    thermal: int = 25           # thermal erosion iterations
    detail: float = 1.0         # fine rock detail added above the simulation resolution
    post: object = None         # fn(ctx, h) -> h, after erosion


def _re_terrace(c, h):
    # erosion softens the steps; bring the strata back, keeping the gullies
    return 0.6 * h + 0.4 * terrace(h, 9, 0.7, 0.1 * c.fbm(3.0, 3, salt=31))


def _mesa_post(c, h):
    return field_apron(_re_terrace(c, h), 0.02 * c.cells, 0.04, bool(c.wrap))


SHAPES = {
    "ALPINE_PEAK": Shape(alpine_peak, erosion=1.6, talus=42.0, detail=1.2),
    "MOUNTAIN_RANGE": Shape(mountain_range, erosion=1.5, talus=42.0, detail=1.1),
    "SNOWY_MASSIF": Shape(snowy_massif, erosion=0.9, talus=38.0, detail=0.8),
    "VOLCANO": Shape(volcano, erosion=1.0, talus=36.0, detail=0.7),
    "DOLOMITES": Shape(dolomites, erosion=0.7, talus=75.0, thermal=6, detail=1.3, post=_dolomite_post),
    "ROLLING_HILLS": Shape(rolling_hills, erosion=0.5, talus=30.0, detail=0.3),
    "HIGHLANDS": Shape(highlands, erosion=1.1, talus=34.0, detail=0.6),
    "FOOTHILLS": Shape(foothills, erosion=1.3, talus=36.0, detail=0.6),
    "CANYON": Shape(canyon, erosion=0.6, talus=55.0, thermal=10, detail=1.0, post=_re_terrace),
    "MESAS": Shape(mesas, erosion=0.6, talus=70.0, thermal=8, detail=0.9, post=_mesa_post),
    "DUNES": Shape(dunes, erosion=0.0, talus=32.0, thermal=40, detail=0.0),
    "BADLANDS": Shape(badlands, erosion=1.8, talus=45.0, thermal=10, detail=0.8),
    "VALLEY": Shape(valley, erosion=1.5, talus=42.0, detail=1.1),
    "VAST": Shape(vast, erosion=1.4, talus=40.0, detail=1.0),
    "FJORD": Shape(fjord, erosion=1.4, talus=45.0, detail=1.1),
    "KARST": Shape(karst, erosion=0.9, talus=60.0, thermal=8, detail=0.8),
    "ARCHIPELAGO": Shape(archipelago, erosion=1.2, talus=38.0, detail=0.7),
    "H_PEAKS": Shape(horizon_peaks, erosion=1.2, talus=42.0, detail=1.0),
    "H_HILLS": Shape(horizon_hills, erosion=0.6, talus=32.0, detail=0.3),
    "H_MESAS": Shape(horizon_mesas, erosion=0.5, talus=70.0, thermal=8, detail=0.8, post=_mesa_post),
    "H_SNOW": Shape(horizon_snow, erosion=0.9, talus=38.0, detail=0.8),
}
