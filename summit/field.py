# SPDX-License-Identifier: GPL-3.0-or-later
"""Heightfield operations: filters, resampling, erosion and the maps the shader reads.

Arrays are indexed [row, column] = [y, x], row 0 at the bottom, which is
also how Blender stores image pixels. ``wrap_x`` makes every operation
treat the x axis as periodic (the horizon ring); y is always clamped.
This module does not use bpy.
"""

import numpy as np


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def normalize(h):
    lo, hi = float(h.min()), float(h.max())
    return (h - lo) / max(hi - lo, 1e-12)


def terrace(h, steps, sharpness=0.8, jitter=None):
    """Stepped plateaus, like layered sedimentary rock. h in 0..1."""
    s = h * steps if jitter is None else h * steps + jitter
    k = np.floor(s)
    f = s - k
    # sharpen the riser of each step; sharpness 0 keeps the slope untouched
    p = 1.0 + sharpness * 7.0
    f = np.where(f < 0.5, 0.5 * (2.0 * f) ** p, 1.0 - 0.5 * (2.0 * (1.0 - f)) ** p)
    return (k + f) / steps


def apron(h, radius, drop, wrap_x=False):
    """Talus cones at the foot of cliffs: fills around steep forms with a gentle slope, keeps the walls."""
    return np.maximum(h, blur(h, radius, wrap_x) - drop)


# -- filtering --------------------------------------------------------------

def _box1d(a, r, axis, wrap):
    n = a.shape[axis]
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="wrap" if wrap else "edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    hi = [slice(None)] * 2
    lo = [slice(None)] * 2
    hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo[axis] = slice(0, n)
    return (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)


def blur(a, radius, wrap_x=False, passes=3):
    """Approximately Gaussian blur (repeated box filters). radius in cells."""
    r = int(round(radius))
    if r < 1:
        return a
    out = a
    for _ in range(passes):
        out = _box1d(out, r, 1, wrap_x)
        out = _box1d(out, r, 0, False)
    return out


def _cubic_axis(a, n_out, axis, wrap):
    """Catmull-Rom resampling along one axis; pixel centres stay aligned."""
    n_in = a.shape[axis]
    if n_in == n_out:
        return a
    pos = (np.arange(n_out) + 0.5) * (n_in / n_out) - 0.5
    i0 = np.floor(pos).astype(np.int64)
    t = pos - i0
    idx = [i0 - 1, i0, i0 + 1, i0 + 2]
    idx = [i % n_in if wrap else np.clip(i, 0, n_in - 1) for i in idx]
    t2, t3 = t * t, t * t * t
    w = [(-t3 + 2 * t2 - t) * 0.5, (3 * t3 - 5 * t2 + 2) * 0.5, (-3 * t3 + 4 * t2 + t) * 0.5, (t3 - t2) * 0.5]
    out = 0.0
    for i, wi in zip(idx, w, strict=True):
        if axis == 0:
            out = out + a[i, :] * wi[:, None]
        else:
            out = out + a[:, i] * wi[None, :]
    return out


def resample(a, ny, nx, wrap_x=False):
    """Smooth (C1) resize, so normal maps of upsampled fields show no grid facets."""
    if a.shape[1] > nx * 2 or a.shape[0] > ny * 2:
        # shrinking a lot: prefilter so fine detail does not alias
        r = max(a.shape[1] / nx, a.shape[0] / ny) * 0.5
        a = blur(a, r, wrap_x, passes=2)
    return _cubic_axis(_cubic_axis(a, nx, 1, wrap_x), ny, 0, False)


def sample(a, fy, fx, wrap_x=False):
    """Bilinear lookup at fractional indices."""
    ny, nx = a.shape
    fy = np.clip(fy, 0.0, ny - 1.0)
    if wrap_x:
        fx = np.mod(fx, nx)
    else:
        fx = np.clip(fx, 0.0, nx - 1.0)
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.minimum(np.floor(fy).astype(np.int64), ny - 2)
    tx = fx - x0
    ty = fy - y0
    x1 = (x0 + 1) % nx if wrap_x else np.minimum(x0 + 1, nx - 1)
    y1 = y0 + 1
    top = a[y1, x0] * (1 - tx) + a[y1, x1] * tx
    bot = a[y0, x0] * (1 - tx) + a[y0, x1] * tx
    return bot * (1 - ty) + top * ty


def gradient(h, wrap_x=False):
    """Central differences (d/dy, d/dx) in height per cell."""
    if wrap_x:
        gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    else:
        gx = np.gradient(h, axis=1)
    gy = np.gradient(h, axis=0)
    return gy, gx


# -- erosion ----------------------------------------------------------------

def _brush(radius):
    offs, ws = [], []
    r = max(radius, 1)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            d = (dx * dx + dy * dy) ** 0.5
            if d < r:
                offs.append((dy, dx))
                ws.append(r - d)
    ws = np.array(ws)
    return np.array(offs, dtype=np.int64), ws / ws.sum()


def erode_hydraulic(h, drops, rng, wrap_x=False, steps=48, inertia=0.1, capacity=6.0, min_capacity=0.005,
                    deposit=0.25, erode=0.35, evaporate=0.015, gravity=8.0, radius=2, batch=24576, max_speed=6.0,
                    progress=None):
    """Particle hydraulic erosion, many droplets at once.

    h is in cell units (height / cell size) so slopes are real gradients.
    Each droplet runs downhill with some inertia, picks up sediment when it
    speeds up and drops it where it slows down. Returns the eroded field,
    a flow map (how much water passed each cell) and a deposit map.
    """
    ny, nx = h.shape
    H = h.astype(np.float64).ravel().copy()
    size = H.size
    flow = np.zeros(size)
    dep_map = np.zeros(size)
    offs, bw = _brush(radius)
    batch = max(1024, min(batch, size // 6))
    done = 0
    while done < drops:
        k = min(batch, drops - done)
        done += k
        x = rng.uniform(0, nx if wrap_x else nx - 1, k)
        y = rng.uniform(0, ny - 1, k)
        dx = np.zeros(k)
        dy = np.zeros(k)
        speed = np.ones(k)
        water = np.ones(k)
        sed = np.zeros(k)
        alive = np.ones(k, dtype=bool)
        for _ in range(steps):
            # dead droplets may sit outside the grid; clamp so indexing stays valid
            if not wrap_x:
                x = np.clip(x, 0.0, nx - 1.0001)
            y = np.clip(y, 0.0, ny - 1.0001)
            ix = np.floor(x).astype(np.int64)
            iy = np.minimum(np.floor(y).astype(np.int64), ny - 2)
            fx = x - ix
            fy = y - iy
            if wrap_x:
                ix %= nx
                ix1 = (ix + 1) % nx
            else:
                ix = np.minimum(ix, nx - 2)
                ix1 = ix + 1
            i00 = iy * nx + ix
            i10 = iy * nx + ix1
            i01 = i00 + nx
            i11 = i10 + nx
            h00, h10, h01, h11 = H[i00], H[i10], H[i01], H[i11]
            gx = (h10 - h00) * (1 - fy) + (h11 - h01) * fy
            gy = (h01 - h00) * (1 - fx) + (h11 - h10) * fx
            hcur = (h00 * (1 - fx) + h10 * fx) * (1 - fy) + (h01 * (1 - fx) + h11 * fx) * fy

            dx = dx * inertia - gx * (1 - inertia)
            dy = dy * inertia - gy * (1 - inertia)
            ln = np.sqrt(dx * dx + dy * dy)
            alive &= ln > 1e-9
            ln = np.maximum(ln, 1e-9)
            dx /= ln
            dy /= ln
            nxp = x + dx
            nyp = y + dy
            if wrap_x:
                nxp %= nx
            else:
                alive &= (nxp >= 0) & (nxp < nx - 1)
            alive &= (nyp >= 0) & (nyp < ny - 1)

            # height at the new position
            jx = np.floor(np.clip(nxp, 0, nx - 1.0001)).astype(np.int64)
            jy = np.floor(np.clip(nyp, 0, ny - 1.0001)).astype(np.int64)
            gx2 = np.clip(nxp, 0, nx - 1.0001) - jx
            gy2 = np.clip(nyp, 0, ny - 1.0001) - jy
            jx1 = (jx + 1) % nx if wrap_x else jx + 1
            j00 = jy * nx + jx
            j10 = jy * nx + jx1
            hnew = ((H[j00] * (1 - gx2) + H[j10] * gx2) * (1 - gy2)
                    + (H[j00 + nx] * (1 - gx2) + H[j10 + nx] * gx2) * gy2)
            dh = np.where(alive, hnew - hcur, 0.0)

            # droplets sharing a cell share its relief, or together they would dig a runaway pit
            share = 1.0 / np.bincount(i00, alive, size)[i00].clip(1.0)
            cap = np.maximum(-dh * speed * water * capacity, min_capacity)
            depositing = alive & ((sed > cap) | (dh > 0))
            amt_dep = np.where(dh > 0, np.minimum(dh * share, sed), (sed - cap) * deposit)
            amt_dep = np.where(depositing, np.maximum(amt_dep, 0.0), 0.0)
            eroding = alive & ~depositing
            amt_ero = np.where(eroding, np.maximum(np.minimum((cap - sed) * erode, -dh) * share, 0.0), 0.0)
            # no erosion at the border: droplets leaving the grid would carve outlet pits there
            border = np.minimum(y, ny - 1 - y)
            if not wrap_x:
                border = np.minimum(border, np.minimum(x, nx - 1 - x))
            amt_ero *= np.clip((border - 1.0) / 6.0, 0.0, 1.0)
            sed += amt_ero - amt_dep

            # deposit on the four corners, erode with a soft brush
            w00 = (1 - fx) * (1 - fy)
            w10 = fx * (1 - fy)
            w01 = (1 - fx) * fy
            w11 = fx * fy
            didx = np.concatenate([i00, i10, i01, i11])
            dval = np.concatenate([amt_dep * w00, amt_dep * w10, amt_dep * w01, amt_dep * w11])
            add = np.bincount(didx, dval, size)
            # brush cells outside the grid are skipped (clamping them would pile erosion on the border)
            by = iy[:, None] + offs[None, :, 0]
            bx = ix[:, None] + offs[None, :, 1]
            inside = (by >= 0) & (by < ny)
            if wrap_x:
                bx = bx % nx
            else:
                inside &= (bx >= 0) & (bx < nx)
            bidx = np.where(inside, by * nx + bx, 0)
            rem = np.bincount(bidx.ravel(), (amt_ero[:, None] * bw[None, :] * inside).ravel(), size)
            H += add - rem
            dep_map += add
            flow += np.bincount(i00, water * alive * np.minimum(speed, 4.0), size)

            speed = np.minimum(np.sqrt(np.maximum(speed * speed - dh * gravity, 0.0)), max_speed)
            water *= 1.0 - evaporate
            x = nxp
            y = nyp
            if not alive.any():
                break
        if progress:
            progress(done / drops)
    return H.reshape(ny, nx), flow.reshape(ny, nx), dep_map.reshape(ny, nx)


def _neighbor(h, dy, dx, wrap_x):
    """h[y+dy, x+dx]; outside the grid it returns h itself (no slope)."""
    r = np.roll(h, (-dy, -dx), (0, 1))
    if dy > 0:
        r[-dy:] = h[-dy:]
    elif dy < 0:
        r[:-dy] = h[:-dy]
    if not wrap_x:
        if dx > 0:
            r[:, -dx:] = h[:, -dx:]
        elif dx < 0:
            r[:, :-dx] = h[:, :-dx]
    return r


def _push(m, dy, dx, wrap_x):
    """Move each cell's value to its (dy, dx) neighbour; values pushed off the grid are dropped."""
    r = np.roll(m, (dy, dx), (0, 1))
    if dy > 0:
        r[:dy] = 0
    elif dy < 0:
        r[dy:] = 0
    if not wrap_x:
        if dx > 0:
            r[:, :dx] = 0
        elif dx < 0:
            r[:, dx:] = 0
    return r


_N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def erode_thermal(h, talus, iterations, rate=0.4, wrap_x=False, mask=None):
    """Material slides down slopes steeper than talus (a gradient) and piles up as scree.

    Returns the new field and how much material settled on each cell.
    """
    h = h.copy()
    gained = np.zeros_like(h)
    for _ in range(iterations):
        moves = []
        total = np.zeros_like(h)
        for dy, dx in _N8:
            dist = 1.41421356 if dy and dx else 1.0
            ex = np.maximum(h - _neighbor(h, dy, dx, wrap_x) - talus * dist, 0.0)
            moves.append(ex)
            total += ex
        # never move more than half the largest drop, so nothing overshoots
        scale = np.where(total > 0, rate * 0.5 * np.maximum.reduce(moves) / np.maximum(total, 1e-12), 0.0)
        if mask is not None:
            scale *= mask
        delta = np.zeros_like(h)
        for (dy, dx), ex in zip(_N8, moves, strict=True):
            m = ex * scale
            delta -= m
            delta += _push(m, dy, dx, wrap_x)
        h += delta
        gained += np.maximum(delta, 0.0)
    return h, gained


# -- detail above the simulation --------------------------------------------

def _hash01(ix, iy, salt):
    """Deterministic pseudo-random 0..1 per integer cell."""
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + salt * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.float32) / 65535.0


def gully_detail(h_m, cell, wavelength, octaves, strength, seed=0, wrap_x=False, mask=None):
    """Erosion-like detail down to the texture resolution.

    Each octave lays short wave segments whose crests run straight downhill,
    blended between jittered cells, so slopes get gullies and spurs aligned
    with the flow. The slope is measured again after every octave, so finer
    gullies branch off the coarser ones, like a real drainage network.
    h_m: heights in metres; cell: texel size in metres (scalar or per-row
    array); wavelength: of the first octave, in texels.
    """
    ny, nx = h_m.shape
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float32)
    h = h_m.astype(np.float32).copy()
    lam = float(wavelength)
    amp_scale = strength
    for o in range(octaves):
        if lam < 2.0:
            break
        f = 1.0 / lam
        gy, gx = gradient(blur(h, lam * 0.35, wrap_x, passes=1), wrap_x)
        gx = gx / cell
        gy = gy / cell
        s = np.sqrt(gx * gx + gy * gy) + 1e-6
        px, py = -gy / s, gx / s           # across the slope: crests run downhill
        cells_x = max(1, int(round(nx * f))) if wrap_x else None
        cx = np.floor(xx * f)
        cy = np.floor(yy * f)
        acc = np.zeros_like(h)
        wsum = np.zeros_like(h)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ix = cx + dx
                iy = cy + dy
                hx = np.mod(ix, cells_x) if wrap_x else ix
                jx = _hash01(hx, iy, seed * 31 + o * 7)
                jy = _hash01(hx, iy, seed * 31 + o * 7 + 1)
                ph = _hash01(hx, iy, seed * 31 + o * 7 + 2) * 6.2831853
                ox = xx - (ix + jx) * lam
                oy = yy - (iy + jy) * lam
                w = np.exp(-(ox * ox + oy * oy) * (f * f) * 1.6)
                acc += w * np.cos((ox * px + oy * py) * (6.2831853 * f * 1.4) + ph)
                wsum += w
        g = acc / np.maximum(wsum, 1e-6)
        # sharp V-shaped gullies, rounded spurs
        g = g - 0.35 * (np.abs(g) - 0.5)
        steep = smoothstep(0.12, 0.7, s)
        amp = lam * np.mean(cell) * amp_scale * steep
        if mask is not None:
            amp = amp * mask
        h += g * amp
        lam *= 0.5
        amp_scale *= 0.9
    return h


def _take(a, oy, ox, wrap_x):
    """a[y+oy, x+ox] with clamped (or wrapped in x) borders."""
    ny, nx = a.shape
    rows = np.clip(np.arange(ny) + oy, 0, ny - 1)
    cols = np.arange(nx) + ox
    cols = np.mod(cols, nx) if wrap_x else np.clip(cols, 0, nx - 1)
    return a[rows][:, cols]


def horizon_ao(h_m, cell, wrap_x=False, directions=12, max_radius=None):
    """Ambient occlusion from the height field: how much sky each texel sees.

    For each direction it marches outward at growing distances and keeps the
    highest horizon, measured against the local tangent plane (so an even
    slope counts as open). Gullies and the feet of walls get dark, ridges
    stay lit.
    """
    ny, nx = h_m.shape
    cell = float(np.mean(cell))
    max_radius = max_radius or max(nx, ny) / 12.0
    steps = []
    d = 1.5
    while d <= max_radius:
        steps.append(d)
        d *= 1.5
    gy, gx = gradient(blur(h_m, 2.0, wrap_x, passes=1), wrap_x)
    gx = gx / cell
    gy = gy / cell
    occl = np.zeros_like(h_m, dtype=np.float32)
    for k in range(directions):
        a = 2.0 * np.pi * (k + 0.5) / directions
        ca, sa = np.cos(a), np.sin(a)
        best = np.full_like(occl, -1e9)
        for d in steps:
            ox, oy = int(round(ca * d)), int(round(sa * d))
            if ox == 0 and oy == 0:
                continue
            dist = np.hypot(ox, oy) * cell
            best = np.maximum(best, (_take(h_m, oy, ox, wrap_x) - h_m) / dist)
        tangent = gx * ca + gy * sa
        occl += np.maximum(best / np.sqrt(1.0 + best * best) - tangent / np.sqrt(1.0 + tangent * tangent), 0.0)
    return np.clip(1.0 - occl / directions, 0.0, 1.0)


# -- maps -------------------------------------------------------------------

def slope(h_m, cell_x, cell_y, wrap_x=False):
    """Gradient magnitude (rise over run) of a height field in metres."""
    gy, gx = gradient(h_m, wrap_x)
    return np.hypot(gx / cell_x, gy / cell_y)


def normal_map(h_m, cell_x, cell_y, wrap_x=False):
    """Unit normals (nx, ny, nz) of a height field in metres, in its own x/y frame."""
    gy, gx = gradient(h_m, wrap_x)
    gx = gx / cell_x
    gy = gy / cell_y
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    return -gx * inv, -gy * inv, inv


def cavity(h_m, cell, wrap_x=False):
    """Concavity 0..1 (0.5 flat, high in gullies, low on ridges), from two blur scales."""
    near = blur(h_m, max(2.0, 6.0 / cell ** 0.25), wrap_x) - h_m
    far = blur(h_m, max(4.0, 24.0 / cell ** 0.25), wrap_x) - h_m
    c = near * 0.6 + far * 0.4
    scale = np.percentile(np.abs(c), 97) + 1e-9
    return np.clip(0.5 + 0.5 * c / scale, 0.0, 1.0)


def flow_mask(flow, wrap_x=False):
    """Log-scaled, softened flow accumulation in 0..1; bright along water channels."""
    f = np.log1p(blur(flow, 1, wrap_x, passes=1))
    hi = np.percentile(f, 99.7) + 1e-9
    lo = np.percentile(f, 70)
    return np.clip((f - lo) / (hi - lo), 0.0, 1.0) ** 1.3
