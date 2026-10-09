# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn generated maps into Blender objects: terrains, horizon rings and water.

A terrain is one grid mesh with:

- its own material, built on the shared ``SM Terrain Surface`` group;
- two packed images (normal map, and masks: flow, sediment, cavity,
  forest), so the .blend renders anywhere without the add-on;
- vertex attributes ``sm_forest``, ``sm_flow`` and ``sm_sediment``, which
  scatter tools can use as masks;
- forest layers (``SM Forest`` modifiers) from its biome;
- optionally a water plane, parented to it.

Its settings are stored on the object, so it can be regenerated with a
new seed or quality, and the material, images and forest settings are
kept.
"""

import math

import bpy
import numpy as np

from . import biomes, field, forest, haze, presets, surface, trees
from .generate import QUALITY, apron_loops, generate, perimeter
from .generate import apron as make_apron

KEY = "summit"
APRON_REACH = 2.0    # surroundings reach this many terrain widths from the centre


# -- images and meshes ------------------------------------------------------

def _write_image(img, name, rgba):
    """Write an (h, w, 4) float array into img (created or resized as needed) and pack it."""
    h, w, _ = rgba.shape
    if img is None:
        img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
    elif tuple(img.size) != (w, h):
        img.scale(w, h)
    img.colorspace_settings.name = "Non-Color"
    img.alpha_mode = "CHANNEL_PACKED"
    img.pixels.foreach_set(np.ascontiguousarray(rgba, dtype=np.float32).ravel())
    img.update()
    img.pack()
    return img


def _grid_quads(rows, cols, flip=False):
    r = np.arange(rows - 1)[:, None]
    c = np.arange(cols - 1)[None, :]
    a = (r * cols + c).ravel()
    quads = np.stack([a, a + 1, a + cols + 1, a + cols], -1)
    return quads[:, ::-1] if flip else quads


def _grid_mesh(name, co, rows, cols, uv, flip=False):
    """A quad grid from (rows*cols, 3) positions and (rows*cols, 2) UVs, built with foreach_set."""
    return _quad_mesh(name, co, _grid_quads(rows, cols, flip), uv)


def _quad_mesh(name, co, quads, uv):
    """A mesh from (n, 3) positions, (f, 4) vertex indices and per-vertex (n, 2) UVs."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", co.astype(np.float32).ravel())
    nf = len(quads)
    me.loops.add(nf * 4)
    me.loops.foreach_set("vertex_index", quads.ravel().astype(np.int32))
    me.polygons.add(nf)
    me.polygons.foreach_set("loop_start", np.arange(0, nf * 4, 4, dtype=np.int32))
    me.update(calc_edges=True)
    layer = me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv[quads.ravel()].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", np.ones(nf, dtype=bool))
    me.validate(clean_customdata=False)
    return me


def _sampler(maps, fy, fx, mesh_px):
    """Sample any map at fractional texel positions, prefiltered to the mesh spacing."""
    ratio = max(1.0, mesh_px)

    def take(a):
        if ratio > 1.5:
            a = field.blur(a, ratio * 0.5, maps.wrap, passes=2)
        return field.sample(a, fy, fx, maps.wrap)
    return take


def _add_attributes(me, take, maps, extra=None):
    """Mask attributes per vertex: sampled for the grid, plus extra {name: values} for apron vertices."""
    values = {"sm_forest": take(maps.forest).ravel(), "sm_flow": take(maps.flow).ravel(),
              "sm_sediment": take(maps.sediment).ravel()}
    if extra:
        values["sm_apron"] = np.zeros(len(values["sm_forest"]), np.float32)
        values = {k: np.concatenate([v, extra[k]]) for k, v in values.items()}
    for key, v in values.items():
        attr = me.attributes.new(key, "FLOAT", "POINT")
        attr.data.foreach_set("value", v.astype(np.float32))


def _mask_rgba(maps):
    return np.stack([maps.flow, maps.sediment, maps.cavity, maps.forest], -1)


def terrain_mesh(name, maps, size, height, res, apron=None):
    """The terrain grid; apron: dict(seed, water, reach) to surround it with low hills out to a circle."""
    ty, tx = maps.h.shape
    u = np.linspace(0.0, 1.0, res)
    U, V = np.meshgrid(u, u)
    take = _sampler(maps, V * ty - 0.5, U * tx - 0.5, tx / res)
    z = take(maps.h) * height
    co = np.stack([(U - 0.5) * size, (V - 0.5) * size, z], -1).reshape(-1, 3)
    uv = np.stack([U, V], -1).reshape(-1, 2)
    quads = _grid_quads(res, res)
    extra = None
    if apron:
        edge = perimeter(res)
        loops = apron_loops(res)
        aco, aforest, ablend = make_apron(co[edge, :2], co[edge, 2], size, height, apron.get("seed", 0),
                                          apron.get("water", -1.0), apron.get("reach", 1.5), loops)
        p = len(edge)
        n0 = len(co)
        # loop k vertex i sits at n0 + k * p + i; loop "-1" is the terrain's own border
        ring = np.concatenate([edge[None], n0 + np.arange(loops * p).reshape(loops, p)], 0)
        i0, i1 = ring[:-1], ring[1:]
        quads = np.concatenate([quads, np.stack([i0, i1, np.roll(i1, -1, 1), np.roll(i0, -1, 1)], -1).reshape(-1, 4)])
        co = np.concatenate([co, aco.reshape(-1, 3)])
        uv = np.concatenate([uv, np.tile(uv[edge], (loops, 1))])   # the border texels, masked by sm_apron
        extra = {"sm_forest": aforest.ravel(), "sm_flow": np.zeros(loops * p, np.float32),
                 "sm_sediment": np.zeros(loops * p, np.float32), "sm_apron": ablend.ravel()}
    me = _quad_mesh(name, co, quads, uv)
    _add_attributes(me, take, maps, extra)
    return me


def ring_mesh(name, maps, radius, depth, height, cols, rows):
    ty, tx = maps.h.shape
    u = np.linspace(0.0, 1.0, cols)   # last column repeats the first, closing the ring with a UV seam
    v = np.linspace(0.0, 1.0, rows)
    U, V = np.meshgrid(u, v)
    take = _sampler(maps, V * ty - 0.5, U * tx - 0.5, tx / cols)
    th = U * 2.0 * math.pi
    r = radius + V * depth
    z = take(maps.h) * height
    co = np.stack([np.cos(th) * r, np.sin(th) * r, z], -1).reshape(-1, 3)
    me = _grid_mesh(name, co, rows, cols, np.stack([U, V], -1).reshape(-1, 2), flip=True)
    _add_attributes(me, take, maps)
    return me


def normal_rgba(maps, ring=False):
    nx, ny, nz = maps.normal
    if ring:
        # field x runs along the ring, y outward: rotate into object space per column
        th = (np.arange(nx.shape[1]) + 0.5) / nx.shape[1] * 2.0 * math.pi
        s, c = np.sin(th)[None, :], np.cos(th)[None, :]
        nx, ny = -nx * s + ny * c, nx * c + ny * s
    rgb = np.stack([nx, ny, nz], -1) * 0.5 + 0.5
    return np.concatenate([rgb, maps.ao[..., None]], -1)   # alpha: ambient occlusion


# -- objects ----------------------------------------------------------------

def settings(obj):
    s = obj.get(KEY) if obj else None
    return s.to_dict() if hasattr(s, "to_dict") else (dict(s) if s else None)


def is_terrain(obj):
    return obj is not None and obj.type == "MESH" and obj.get(KEY) is not None


def _progress(context):
    wm = context.window_manager if context else None
    if wm is None:
        return lambda f, label="": None, lambda: None
    wm.progress_begin(0, 100)
    return (lambda f, label="": wm.progress_update(int(f * 100))), wm.progress_end


def _maps_for(s, report):
    ring = (s["radius"], s["depth"]) if s["kind"] == "HORIZON" else None
    return generate(s["shape"], s["seed"], s["quality"], s["size"], s["height"], s["erosion"], s["falloff"],
                    ring=ring, progress=report)


def _build_mesh(name, s, maps):
    if s["kind"] == "HORIZON":
        res = QUALITY[s["quality"]][2]
        return ring_mesh(name, maps, s["radius"], s["depth"], s["height"], res * 2, max(48, res // 5))
    apron = None
    if s.get("apron"):
        apron = {"seed": s["seed"], "water": s.get("water", -1.0), "reach": APRON_REACH}
    return terrain_mesh(name, maps, s["size"], s["height"], QUALITY[s["quality"]][2], apron)


def forest_values(f, s, vp_cap=60000):
    area = s["size"] ** 2 * (2.5 if s.get("apron") else 1.0)
    estimate = area / 10000.0 * f.density * 0.3
    water = s.get("water", -1.0)
    return {
        "Density": f.density,
        "Tree Line": f.top,
        "Lowest": max(f.bottom, water + 0.008) if water > -0.5 else f.bottom,
        "Tree Height": f.height,
        "Max Slope": math.radians(f.max_slope),
        "Min Distance": max(0.8, f.height * 0.16),
        "Terrain Height": s["height"],
        "Viewport Amount": float(min(1.0, vp_cap / max(estimate, 1.0))),
    }


def add_forests(obj, biome_id):
    s = settings(obj)
    for f in biomes.BIOME_BY_ID[biome_id].forests:
        coll = trees.species_collection(f.species)
        forest.add_layer(obj, coll, f"SM {trees.SPECIES[f.species]['label']} Forest", **forest_values(f, s))


def remove_forests(obj):
    for mod in forest.layers(obj):
        obj.modifiers.remove(mod)


def water_object(obj):
    return next((c for c in obj.children if c.get("sm_water")), None)


def _drive_water_level(obj, water, height):
    """The shader's Water Level follows the water plane, so moving the plane moves the shore."""
    node = surface.surface_node(obj.active_material)
    if node is None:
        return
    sock = node.inputs["Water Level"]
    sock.driver_remove("default_value")
    if water is None:
        sock.default_value = -1.0
        return
    fc = sock.driver_add("default_value")
    d = fc.driver
    d.type = "SCRIPTED"
    var = d.variables.new()
    var.name = "z"
    var.type = "TRANSFORMS"
    var.targets[0].id = water
    var.targets[0].transform_type = "LOC_Z"
    var.targets[0].transform_space = "LOCAL_SPACE"
    d.expression = f"z / {height:.4f}"


def _water(obj, s):
    """Create, move or remove the water plane that belongs to obj."""
    water = water_object(obj)
    level = s.get("water", -1.0)
    if level <= -0.5 or s["kind"] == "HORIZON":
        if water is not None:
            bpy.data.objects.remove(water)
        _drive_water_level(obj, None, s["height"])
        return None
    if water is None:
        me = bpy.data.meshes.new(f"{obj.name} Water")
        if s.get("apron"):   # round, like the surroundings
            th = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False)
            me.from_pydata([(0.5 * math.cos(a), 0.5 * math.sin(a), 0.0) for a in th], [], [tuple(range(96))])
        else:
            h = 0.5
            me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
        b = biomes.BIOME_BY_ID[s["biome"]]
        mname = f"SM Water {b.label}"
        mat = bpy.data.materials.get(mname) or surface.water_material(mname, *b.water)
        me.materials.append(mat)
        water = bpy.data.objects.new(f"{obj.name} Water", me)
        water["sm_water"] = True
        for coll in obj.users_collection:
            coll.objects.link(water)
        water.parent = obj
    extent = s["size"] * (2.0 * APRON_REACH + 0.1 if s.get("apron") else 1.0)
    water.scale = (extent, extent, 1.0)
    water.location = (0.0, 0.0, level * s["height"])
    _drive_water_level(obj, water, s["height"])
    return water


def set_water(obj, level):
    """Water at level (fraction of the height), or none for level -1. Forests stay out of the water."""
    s = settings(obj)
    s["water"] = float(level)
    obj[KEY] = s
    _water(obj, s)
    for mod in forest.layers(obj):
        low = forest.get(mod, "Lowest")
        if level > -0.5 and low < level + 0.008:
            forest.set_value(mod, "Lowest", level + 0.008)


def create(context, s, name, location=(0.0, 0.0, 0.0)):
    """Generate a new terrain or horizon object from settings s and link it to the active collection."""
    report, done = _progress(context)
    try:
        maps = _maps_for(s, report)
        me = _build_mesh(name, s, maps)
        nimg = _write_image(None, f"{name} Normal", normal_rgba(maps, s["kind"] == "HORIZON"))
        mimg = _write_image(None, f"{name} Masks", _mask_rgba(maps))
    finally:
        done()
    haze.ensure(context.scene, s["haze"])
    extra = {}
    if s["kind"] == "HORIZON":
        extra.update({"Detail Distance": 50.0, "Macro Variation": 0.7})
    mat = surface.terrain_material(f"{name}", nimg, mimg, s["height"], s["biome"], extra)
    me.materials.append(mat)
    obj = bpy.data.objects.new(name, me)
    obj[KEY] = s
    obj.location = location
    context.collection.objects.link(obj)
    if s["kind"] == "TERRAIN" and s.get("forests", True):
        add_forests(obj, s["biome"])
    _water(obj, s)
    return obj


def regenerate(context, obj, **changes):
    """Rebuild obj's shape with changed settings, keeping its material, images and forests."""
    s = settings(obj)
    s.update(changes)
    report, done = _progress(context)
    try:
        maps = _maps_for(s, report)
        old = obj.data
        me = _build_mesh(old.name, s, maps)
        for m in old.materials:
            me.materials.append(m)
        mat = old.materials[0] if old.materials else None
        node = surface.surface_node(mat)
        if node is not None:
            for link in mat.node_tree.links:
                if link.to_socket == node.inputs["Normal"]:
                    nmap = link.from_node
                    tex = nmap.inputs["Color"].links[0].from_node
                    _write_image(tex.image, tex.image.name, normal_rgba(maps, s["kind"] == "HORIZON"))
                if link.to_socket == node.inputs["Flow"]:
                    tex = link.from_node.inputs["Color"].links[0].from_node
                    _write_image(tex.image, tex.image.name, _mask_rgba(maps))
            node.inputs["Terrain Height"].default_value = s["height"]
    finally:
        done()
    obj.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    obj[KEY] = s
    for mod in forest.layers(obj):
        forest.set_value(mod, "Terrain Height", s["height"])
    _water(obj, s)
    return obj


def set_biome(obj, biome_id, forests=True):
    """Re-dress a terrain: new surface values, and new forest layers if asked."""
    s = settings(obj)
    s["biome"] = biome_id
    obj[KEY] = s
    node = surface.surface_node(obj.active_material)
    if node is not None:
        surface.apply_values(node, biomes.surface_values(biome_id))
    if s["kind"] == "TERRAIN" and forests:
        remove_forests(obj)
        add_forests(obj, biome_id)
    water = water_object(obj)
    if water is not None:
        b = biomes.BIOME_BY_ID[biome_id]
        mname = f"SM Water {b.label}"
        water.data.materials[0] = bpy.data.materials.get(mname) or surface.water_material(mname, *b.water)


def terrain_settings(preset_id, seed=0, quality="MEDIUM", size=None, height=None, erosion=1.0, biome=None,
                     forests=True, water=True, surroundings=True):
    p = presets.PRESET_BY_ID[preset_id]
    return {
        "kind": "TERRAIN", "preset": p.id, "shape": p.id, "seed": int(seed), "quality": quality,
        "size": float(size or p.size), "height": float(height or p.height), "erosion": float(erosion),
        "falloff": p.falloff, "biome": biome or p.biome, "water": p.water if water else -1.0,
        "haze": p.haze, "forests": bool(forests), "apron": bool(surroundings),
    }


def horizon_settings(style, seed=0, quality="MEDIUM", radius=4000.0, depth=3000.0, height=None, biome=None):
    _sid, _label, _desc, default_biome, default_height = presets.HORIZON_BY_ID[style]
    return {
        "kind": "HORIZON", "preset": style, "shape": style, "seed": int(seed), "quality": quality,
        "size": float(radius + depth) * 2.0, "height": float(height or default_height), "erosion": 1.0,
        "falloff": 0.0, "biome": biome or default_biome, "water": -1.0, "haze": 0.12,
        "radius": float(radius), "depth": float(depth), "forests": False,
    }


# -- scene helpers ------------------------------------------------------------

# which distant range suits each biome, and its height relative to the terrain
HORIZON_FOR_BIOME = {
    "ARCTIC": ("H_SNOW", 1.1), "MEADOW": ("H_HILLS", 1.6), "HIGHLAND": ("H_HILLS", 1.3),
    "TROPICAL": ("H_HILLS", 1.4), "FOREST": ("H_HILLS", 1.3), "CANYON": ("H_MESAS", 1.2),
    "DESERT": ("H_MESAS", 1.2), "DUNES": ("H_MESAS", 1.6), "BADLANDS": ("H_MESAS", 1.4),
}


def horizon_object(obj):
    return next((c for c in obj.children if is_terrain(c) and settings(c)["kind"] == "HORIZON"), None)


def add_distant_mountains(context, obj):
    """A horizon ring just beyond the terrain's surroundings, dressed in the same biome and parented to it."""
    s = settings(obj)
    style, factor = HORIZON_FOR_BIOME.get(s["biome"], ("H_PEAKS", 1.0))
    reach = APRON_REACH if s.get("apron") else 0.75
    quality = "HIGH" if s["quality"] in ("HIGH", "ULTRA") else "MEDIUM"
    h = horizon_settings(style, s["seed"] + 1, quality, radius=reach * s["size"] * 0.92, depth=s["size"] * 2.0,
                         height=s["height"] * factor, biome=s["biome"])
    ring = create(context, h, f"{obj.name} Horizon", obj.matrix_world.translation.copy())
    ring.parent = obj
    ring.matrix_parent_inverse = obj.matrix_world.inverted()
    return ring


def _peak(obj):
    """Highest vertex of the terrain grid (not its surroundings), in object space."""
    s = settings(obj)
    res = QUALITY[s["quality"]][2]
    co = np.empty(len(obj.data.vertices) * 3, np.float32)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)[: res * res] if s["kind"] == "TERRAIN" else co.reshape(-1, 3)
    return co[int(np.argmax(co[:, 2]))]


def _sun_direction(scene):
    """Unit vector towards the scene's sun (the first sun lamp), or a default afternoon sun."""
    from mathutils import Vector

    for o in scene.objects:
        if o.type == "LIGHT" and o.data.type == "SUN":
            return (o.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    el, az = math.radians(30.0), math.radians(40.0)
    return Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))


def frame_shot(context, obj, view=0, elevation=0.1, lens=35.0):
    """Put the scene camera inside the landscape, on a well-composed view.

    Tries many camera spots and headings and scores what each would see
    with a coarse grid of rays: land filling about two thirds of the frame,
    layered depth from foreground to horizon, a varied skyline, water when
    there is some, side light from the sun, and no wall right in front of
    the lens. view: 0 is the best view, 1 the next best elsewhere, and so
    on. elevation: base camera height above the ground, as a fraction of
    the terrain height. Returns the camera.
    """
    from mathutils import Euler, Vector

    s = settings(obj)
    scene = context.scene
    size, height = s["size"], s["height"]
    water = s.get("water", -1.0) * height if s.get("water", -1.0) > -0.5 else None
    reach = (APRON_REACH if s.get("apron") else 0.5) * size
    rng = np.random.default_rng(s["seed"] * 7 + 11)
    world = obj.matrix_world
    yaw0 = world.to_euler().z
    sun = np.array(world.to_3x3().inverted() @ _sun_direction(scene))
    sun_local = math.atan2(sun[1], sun[0])
    aspect = scene.render.resolution_y / max(scene.render.resolution_x, 1)
    tan_w = 18.0 / lens                       # 36 mm sensor width
    tan_h = tan_w * aspect
    far = size * 8.0

    def cast(o, d, limit=far):
        """(distance, facing the sun, inside the terrain itself rather than its surroundings)."""
        hit, loc, nrm, _i = obj.ray_cast(Vector(o), Vector(d), distance=limit)
        if not hit:
            return None, 0.0, False
        own = abs(loc.x) < size * 0.5 and abs(loc.y) < size * 0.5
        return (Vector(loc) - Vector(o)).length, float(np.dot(nrm, sun)), own

    def ground(x, y):
        t, _lit, _own = cast((x, y, height * 4.0), (0.0, 0.0, -1.0))
        z = None if t is None else height * 4.0 - t
        g = 0.0 if z is None else z
        return max(g, water) if water is not None else g

    # a fan of rays per heading: 16 columns across the frame, 12 rows spanning well above and below it
    cols = np.linspace(-1.0, 1.0, 16) * tan_w
    rows = np.linspace(-2.2, 3.6, 14) * tan_h
    peak = Vector(_peak(obj))

    def look(eye, yaw):
        fwd = np.array((math.cos(yaw), math.sin(yaw), 0.0))
        right = np.array((math.sin(yaw), -math.cos(yaw), 0.0))
        dist = np.full((len(rows), len(cols)), np.inf)
        wet = np.zeros(dist.shape, bool)
        lit = np.zeros(dist.shape)
        own = np.zeros(dist.shape, bool)
        for i, tv in enumerate(rows):
            for j, tu in enumerate(cols):
                d = fwd + right * tu + np.array((0.0, 0.0, tv))
                d /= np.linalg.norm(d)
                t, lit[i, j], own[i, j] = cast(eye, d)
                if water is not None and d[2] < 0.0:
                    tw = (water - eye[2]) / d[2]
                    if tw > 0.0 and (t is None or tw < t):
                        t, wet[i, j], lit[i, j] = tw, True, 0.5
                if t is not None:
                    dist[i, j] = t
        hit = np.isfinite(dist)
        if not hit.any() or hit.all():
            return None
        # the skyline: the highest row that hits land, per column (as a slope tan)
        top = np.array([rows[np.nonzero(hit[:, j])[0].max()] if hit[:, j].any() else rows[0]
                        for j in range(len(cols))])
        # the real skyline may lie up to one probe row higher than the last row that hit
        top = top + (rows[1] - rows[0]) * hit.any(axis=0)
        # tilt so the skyline sits in the upper third of the frame, with the highest summit inside it
        pitch = max(math.atan(float(np.median(top))) - math.atan(0.3 * tan_h),
                    math.atan(float(top.max())) - math.atan(0.8 * tan_h))
        pitch = max(min(pitch, math.radians(25.0)), math.radians(-30.0))
        # a summit cut off by the top of the frame (or above the highest probe ray) ruins the shot
        clipped = bool(hit[-1].any()) or math.atan(float(top.max())) > pitch + math.atan(0.95 * tan_h)
        lo, hi = math.tan(pitch) - tan_h, math.tan(pitch) + tan_h
        inside = (rows >= lo) & (rows <= hi)
        if inside.sum() < 3:
            return None
        f_hit, f_dist, f_wet = hit[inside], dist[inside], wet[inside]
        land = f_hit.mean()
        near = (f_dist < max(0.1 * size, 60.0)).mean() + 0.5 * (f_dist < 0.25 * size).mean()
        # land in sunlight rather than its own shadow (a rough test: facing the sun)
        sunny = float((lit[inside][f_hit] > 0.2).mean()) if f_hit.any() else 0.0
        # a landscape, not a close-up: most of what we see about a terrain's width away, and some far land
        spread = float(np.median(f_dist[f_hit])) / size if f_hit.any() else 0.0
        breadth = 1.0 - min(abs(math.log(max(spread, 1e-3))) / math.log(4.0), 1.0)
        far_land = float((f_dist[f_hit] > 1.5 * size).mean()) if f_hit.any() else 0.0
        # the subject: the terrain itself, not just its surroundings
        subject = float(own[inside].mean())
        depth = float(np.std(np.log(f_dist[f_hit]))) if f_hit.sum() > 3 else 0.0
        skyline = float(np.std(top)) / tan_h
        rel = (sun_local - yaw + math.pi) % (2.0 * math.pi) - math.pi
        side_light = math.sin(abs(rel)) * (1.0 if abs(rel) > math.radians(40.0) else 0.5)
        score = (1.5 * (1.0 - min(abs(land - 0.62) * 2.5, 1.0)) + min(depth, 1.2) + 2.0 * min(skyline * 3.0, 1.0)
                 - 5.0 * near + 0.8 * side_light + 1.0 * sunny + 2.0 * breadth + min(far_land * 4.0, 1.0)
                 + 2.5 * min(subject * 2.5, 1.0))
        if water is not None:
            score += 2.5 * min(f_wet.mean() * 5.0, 1.0) - (2.5 if not f_wet.any() else 0.0)
        if clipped:
            score -= 3.0
        return score, pitch

    results = []
    radius = min(reach * 0.8, size * 1.25)
    for _ in range(80):
        a = rng.uniform(0.0, 2.0 * math.pi)
        r = radius * math.sqrt(rng.uniform(0.02, 1.0))
        x, y = r * math.cos(a), r * math.sin(a)
        # low terrains (dunes, hills) need a higher eye than their height alone suggests
        z = ground(x, y) + max(2.0, max(elevation * height, 0.02 * size) * rng.choice((0.4, 1.0, 2.0)))
        eye = np.array((x, y, z))
        to_peak = math.atan2(peak.y - y, peak.x - x)
        for k in range(6):
            yaw = to_peak + k * math.pi / 3.0
            got = look(eye, yaw)
            if got:
                results.append((got[0], eye, yaw, got[1]))
    if not results:
        results.append((0.0, np.array((0.0, -size, height)), math.pi / 2, 0.0))
    results.sort(key=lambda r: -r[0])
    # the view-th best, skipping near-duplicates of better ones
    picked = []
    for res in results:
        if all(np.linalg.norm(res[1][:2] - p[1][:2]) > 0.15 * size
               or abs((res[2] - p[2] + math.pi) % (2.0 * math.pi) - math.pi) > math.radians(45.0) for p in picked):
            picked.append(res)
        if len(picked) > view:
            break
    _score, eye, yaw, pitch = picked[min(view, len(picked) - 1)]

    cam = scene.camera
    if cam is None or cam.type != "CAMERA":
        cam = bpy.data.objects.new("Summit Camera", bpy.data.cameras.new("Summit Camera"))
        scene.collection.objects.link(cam)
        scene.camera = cam
    cam.data.lens = lens
    cam.data.sensor_width = 36.0
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.clip_start = 0.5
    cam.data.clip_end = size * 12.0
    cam.location = world @ Vector(eye)
    cam.rotation_euler = Euler((math.pi / 2 + pitch, 0.0, yaw - math.pi / 2 + yaw0))
    return cam
