# SPDX-License-Identifier: GPL-3.0-or-later
"""Render preview thumbnails for every landform and horizon style.

    blender -b --factory-startup --python tools/render_thumbnails.py [-- [--res N] [--out DIR] [--quality Q] [NAME ...]]

Writes PNGs into summit/thumbs (T_<ID>.png). NAME filters by preset id.
Each landform is shown as a user gets it: with its surroundings and
distant mountains, from the camera Frame Shot picks.
Uses the Open Sky add-on for lighting when its repository sits next to
this one (../open-sky); otherwise a plain sun and sky.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "open-sky"))

import bpy  # noqa: E402
import render_gpu  # noqa: E402
from mathutils import Vector  # noqa: E402

import summit  # noqa: E402

summit.register()
from summit import ops, presets, terrain, thumbs  # noqa: E402

try:
    import open_sky  # noqa: E402

    open_sky.register()
    from open_sky import rig  # noqa: E402
except ImportError:
    rig = None

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RES, OUT, QUALITY, SAMPLES = 256, thumbs.DIR, "PREVIEW", 32
names = []
i = 0
while i < len(argv):
    if argv[i] in ("--res", "--out", "--quality", "--samples"):
        v = argv[i + 1]
        RES = int(v) if argv[i] == "--res" else RES
        OUT = v if argv[i] == "--out" else OUT
        QUALITY = v.upper() if argv[i] == "--quality" else QUALITY
        SAMPLES = int(v) if argv[i] == "--samples" else SAMPLES
        i += 2
    else:
        names.append(argv[i].upper())
        i += 1


def wanted(key):
    return not names or any(n in key for n in names)


def reset(sun_el=22.0, sun_az=40.0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    render_gpu.enable(sc)
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.view_settings.exposure = -0.6
    if rig is not None:
        world = rig.create(sc)
        node = rig.sky_node(world)
        for k, v in {"Haze Density": 0.0, "Cloud Coverage": 0.0, "Ground": 0.0}.items():
            if k in node.inputs:
                node.inputs[k].default_value = v
        rig.set_sun_angles(rig.sun_object(world), math.radians(sun_el), math.radians(sun_az))
    else:
        sc.view_settings.exposure = 0.0
        world = bpy.data.worlds.new("sky")
        world.color = (0.35, 0.45, 0.6)
        sc.world = world
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.data.energy = 4.0
        sun.rotation_euler = (math.radians(90 - sun_el), 0, math.radians(sun_az))
        sc.collection.objects.link(sun)
    ops.ensure_transparency(bpy.context)
    return sc


def camera(sc, loc, target, lens):
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = lens
    cam.data.clip_end = 100000.0
    sc.collection.objects.link(cam)
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam


def save(sc, key):
    sc.render.resolution_x = sc.render.resolution_y = RES
    os.makedirs(OUT, exist_ok=True)
    sc.render.filepath = os.path.join(OUT, f"T_{key}.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", sc.render.filepath)


# Frame Shot views that make better icons than the first one
THUMB_VIEW = {"MOUNTAIN_RANGE": 1, "FOOTHILLS": 1}

for p in presets.PRESETS:
    if not wanted(p.id):
        continue
    sc = reset()
    s = terrain.terrain_settings(p.id, 0, QUALITY)
    obj = terrain.create(bpy.context, s, p.label)
    terrain.add_distant_mountains(bpy.context, obj)
    sc.render.resolution_x = sc.render.resolution_y = RES
    bpy.context.view_layer.update()
    # a longer lens: the landform should fill a small icon
    terrain.frame_shot(bpy.context, obj, THUMB_VIEW.get(p.id, 0), lens=40.0)
    save(sc, p.id)

for sid, label, _desc, _biome, _h in presets.HORIZONS:
    if not wanted(sid):
        continue
    sc = reset(sun_el=16.0)
    s = terrain.horizon_settings(sid, 0, QUALITY)
    # ground in front of the ring, in the same biome, so the ring isn't floating over nothing
    g = terrain.terrain_settings("ROLLING_HILLS", 0, QUALITY, biome=s["biome"], forests=False)
    terrain.create(bpy.context, g, "Ground")
    terrain.create(bpy.context, s, label)
    camera(sc, (0.0, 0.0, 230.0), (0.0, s["radius"] + s["depth"] * 0.45, s["height"] * 0.35), 55.0)
    save(sc, sid)
