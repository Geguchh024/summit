# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the README images.

    blender -b --factory-startup --python tools/render_showcase.py [-- [--samples N] [--scale F] [JOB ...]]

JOB is any of: hero canyon volcano dolomites dunes fjord gallery trees landforms (default: all).
Writes into docs/images. Lighting comes from the Open Sky add-on
(../open-sky) when available.
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
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

import summit  # noqa: E402

summit.register()
from summit import ops, presets, terrain, thumbs, trees  # noqa: E402

try:
    import open_sky  # noqa: E402

    open_sky.register()
    from open_sky import rig  # noqa: E402
except ImportError:
    rig = None

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 96
SCALE = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 1.0
jobs = [a for a in argv if not a.startswith("--") and not a.replace(".", "").isdigit()]
OUT = os.path.join(ROOT, "docs", "images")


def reset(sun_el=22.0, sun_az=40.0, haze=0.0):
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
        for k, v in {"Haze Density": haze, "Cloud Coverage": 0.0, "Ground": 0.0}.items():
            if k in node.inputs:
                node.inputs[k].default_value = v
        rig.set_sun_angles(rig.sun_object(world), math.radians(sun_el), math.radians(sun_az))
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


def save(sc, name, w, h):
    sc.render.resolution_x, sc.render.resolution_y = int(w * SCALE), int(h * SCALE)
    os.makedirs(OUT, exist_ok=True)
    sc.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("wrote", sc.render.filepath)


def scene_shot(sc, preset, quality, view=0, lens=35.0, seed=0, w=1600, h=800, **kw):
    """A terrain as a user gets it: surroundings, distant mountains and a Frame Shot camera."""
    s = terrain.terrain_settings(preset, seed, quality, **kw)
    obj = terrain.create(bpy.context, s, presets.PRESET_BY_ID[preset].label)
    terrain.add_distant_mountains(bpy.context, obj)
    sc.render.resolution_x, sc.render.resolution_y = int(w * SCALE), int(h * SCALE)
    bpy.context.view_layer.update()
    terrain.frame_shot(bpy.context, obj, view, lens=lens)
    return obj


def terrain_shot(name, preset, view=0, lens=35.0, quality="HIGH", sun=(22.0, 40.0), **kw):
    sc = reset(*sun)
    scene_shot(sc, preset, quality, view, lens, **kw)
    save(sc, name, 1600, 800)


def gallery():
    """All library thumbnails in one sheet."""
    order = [p.id for p in presets.PRESETS] + [h[0] for h in presets.HORIZONS]
    cols, n = 7, 256
    rows = (len(order) + cols - 1) // cols
    sheet = np.ones((rows * n, cols * n, 4), np.float32)
    for i, key in enumerate(order):
        img = bpy.data.images.load(os.path.join(thumbs.DIR, f"T_{key}.png"))
        a = np.array(img.pixels[:], np.float32).reshape(img.size[1], img.size[0], 4)
        r, c = divmod(i, cols)
        r = rows - 1 - r
        sheet[r * n:(r + 1) * n, c * n:(c + 1) * n] = a[:n, :n]
    out = bpy.data.images.new("gallery", cols * n, rows * n, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = os.path.join(OUT, "gallery.png")
    out.file_format = "PNG"
    out.save()
    print("wrote", out.filepath_raw)


def tree_lineup():
    sc = reset(sun_el=32.0, sun_az=215.0)   # behind the camera, to the left
    bpy.ops.mesh.primitive_plane_add(size=300)
    ground = bpy.context.object
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.09, 0.12, 0.04, 1.0)
    ground.data.materials.append(mat)
    x = -36.0
    k = 0
    for sp in trees.SPECIES:
        coll = trees.species_collection(sp)
        for o in coll.objects[:2]:
            single = bpy.data.collections.new(o.name + " single")
            single.objects.link(o)
            inst = bpy.data.objects.new(o.name, None)
            inst.instance_type = "COLLECTION"
            inst.instance_collection = single
            s = 4.0 if sp == "SHRUB" else 15.0
            inst.scale = (s, s, s)
            # turned and staggered, as in a forest: coplanar cards side by side would flicker
            inst.location = (x, (k % 2) * 9.0, 0.0)
            inst.rotation_euler.z = 0.6 + k * 1.3
            sc.collection.objects.link(inst)
            x += 4.0 if sp == "SHRUB" else 8.0
            k += 1
    camera(sc, (0.0, -62.0, 6.0), (0.0, 4.0, 8.0), 38.0)
    save(sc, "trees", 1600, 600)


# Frame Shot's second view composes these better than its first
LANDFORM_VIEW = {"DOLOMITES": 1, "DUNES": 1}


def landforms(only=()):
    """One 16:9 render per landform, for the website strip."""
    for p in presets.PRESETS:
        if only and p.id not in only:
            continue
        sc = reset()
        scene_shot(sc, p.id, "HIGH", LANDFORM_VIEW.get(p.id, 0), 32.0, w=1280, h=720)
        os.makedirs(os.path.join(OUT, "landforms"), exist_ok=True)
        sc.render.filepath = os.path.join(OUT, "landforms", p.id.lower().replace("_", "-") + ".png")
        bpy.ops.render.render(write_still=True)
        print("wrote", sc.render.filepath)


ALL = {
    "hero": lambda: terrain_shot("hero", "ALPINE_PEAK", quality="ULTRA", sun=(18.0, 40.0)),
    "canyon": lambda: terrain_shot("canyon", "CANYON", sun=(26.0, 60.0)),
    "volcano": lambda: terrain_shot("volcano", "VOLCANO"),
    "dolomites": lambda: terrain_shot("dolomites", "DOLOMITES", view=1, lens=30.0),
    "dunes": lambda: terrain_shot("dunes", "DUNES", view=1, sun=(14.0, 80.0)),
    "fjord": lambda: terrain_shot("fjord", "FJORD", lens=30.0),
    "gallery": gallery,
    "trees": tree_lineup,
    "landforms": landforms,
}
# landforms:ID,ID renders only those landforms
for job in [j for j in jobs if j.startswith("landforms:")]:
    ids = tuple(job.split(":", 1)[1].upper().split(","))
    ALL[job] = lambda ids=ids: landforms(ids)
for job in jobs or list(ALL):
    ALL[job]()
