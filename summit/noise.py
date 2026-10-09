# SPDX-License-Identifier: GPL-3.0-or-later
"""Vectorised gradient noise for numpy: Perlin, fBm, ridged multifractal and Voronoi.

Everything works on coordinate arrays, so a whole heightfield is evaluated
in one call. Every function takes an optional ``wrap``: the width of the
domain in x. With it the noise tiles seamlessly in x, which the horizon ring
needs so the mountains meet at the seam. This module does not use bpy.
"""

import numpy as np


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


class Noise:
    def __init__(self, seed):
        rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
        p = rng.permutation(256).astype(np.int64)
        self.perm = np.concatenate([p, p])
        a = rng.uniform(0.0, 2.0 * np.pi, 256)
        self.gx = np.cos(a)
        self.gy = np.sin(a)
        self.rnd = rng.random(256)

    def _hash(self, ix, iy, salt):
        p = self.perm
        return p[(p[(ix + salt) & 255] + iy) & 255]

    @staticmethod
    def _period(freq, wrap):
        """Snap a frequency so it tiles over wrap; returns (freq, period in cells)."""
        if not wrap:
            return freq, None
        cells = max(1, int(round(freq * wrap)))
        return cells / wrap, cells

    def perlin(self, x, y, period=None, salt=0):
        """Gradient noise in about -1..1. period: lattice cells after which x repeats."""
        x0 = np.floor(x)
        y0 = np.floor(y)
        fx = x - x0
        fy = y - y0
        ix = x0.astype(np.int64)
        iy = y0.astype(np.int64)
        if period:
            ix %= period
            ix1 = (ix + 1) % period
        else:
            ix1 = ix + 1
        iy1 = iy + 1

        def corner(hx, hy, dx, dy):
            h = self._hash(hx, hy, salt)
            return self.gx[h] * dx + self.gy[h] * dy

        u = _fade(fx)
        v = _fade(fy)
        a = corner(ix, iy, fx, fy)
        b = corner(ix1, iy, fx - 1.0, fy)
        c = corner(ix, iy1, fx, fy - 1.0)
        d = corner(ix1, iy1, fx - 1.0, fy - 1.0)
        ab = a + (b - a) * u
        cd = c + (d - c) * u
        return (ab + (cd - ab) * v) * 1.41421356

    def fbm(self, x, y, freq, octaves=6, lacunarity=2.0, gain=0.5, wrap=None, salt=0, billow=False):
        """Fractal Brownian motion in about -1..1. billow folds each octave into soft lumps."""
        total = np.zeros_like(x, dtype=np.float64)
        amp = 1.0
        norm = 0.0
        for o in range(octaves):
            f, period = self._period(freq * lacunarity ** o, wrap)
            n = self.perlin(x * f, y * f, period, salt + o * 59)
            if billow:
                n = np.abs(n) * 2.0 - 1.0
            total += n * amp
            norm += amp
            amp *= gain
        return total / norm

    def ridged(self, x, y, freq, octaves=7, lacunarity=2.0, gain=2.0, persistence=0.5, offset=1.0,
               wrap=None, salt=0):
        """Ridged multifractal (Musgrave) in about 0..1: sharp crests, smooth valleys.

        Each octave is weighted by the previous one, so detail gathers on
        the ridges and valleys stay clean, like real eroded mountains.
        """
        total = np.zeros_like(x, dtype=np.float64)
        weight = np.ones_like(x, dtype=np.float64)
        amp = 1.0
        norm = 0.0
        for o in range(octaves):
            f, period = self._period(freq * lacunarity ** o, wrap)
            n = self.perlin(x * f, y * f, period, salt + o * 61)
            s = offset - np.abs(n)
            s *= s
            s *= weight
            weight = np.clip(s * gain, 0.0, 1.0)
            total += s * amp
            norm += amp
            amp *= persistence
        return total / (norm * offset * offset)

    def voronoi(self, x, y, freq, jitter=1.0, wrap=None, salt=0):
        """(F1, F2, cell random 0..1) of jittered-grid Voronoi cells."""
        f, period = self._period(freq, wrap)
        xs = x * f
        ys = y * f
        ix = np.floor(xs).astype(np.int64)
        iy = np.floor(ys).astype(np.int64)
        fx = xs - ix
        fy = ys - iy
        f1 = np.full(xs.shape, 9.0)
        f2 = np.full(xs.shape, 9.0)
        cid = np.zeros(xs.shape)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                cx = ix + dx
                if period:
                    cx = cx % period
                cy = iy + dy
                px = dx + jitter * self.rnd[self._hash(cx, cy, salt)] + (1.0 - jitter) * 0.5
                py = dy + jitter * self.rnd[self._hash(cx, cy, salt + 101)] + (1.0 - jitter) * 0.5
                d = np.hypot(px - fx, py - fy)
                closer = d < f1
                f2 = np.where(closer, f1, np.minimum(f2, d))
                cid = np.where(closer, self.rnd[self._hash(cx, cy, salt + 202)], cid)
                f1 = np.where(closer, d, f1)
        return f1, f2, cid
