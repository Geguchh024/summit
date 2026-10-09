# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Verdant's procedural trees into the transparent card images Summit's forests use.

    blender -b --factory-startup --python tools/bake_tree_cards.py [-- [--height PX] [--samples N] [NAME ...]]

Needs the Verdant repository next to this one (../verdant). Each tree
variant is rendered three times with a transparent background: from the
front, from the side and from above. The three views go side by side into
two atlases:

- summit/cards/<NAME>.png: albedo (the diffuse colour pass) and alpha;
- summit/cards/<NAME>_N.png: the normal, in the card's own frame
  (x along the card, y up the card, z toward the viewer), and in alpha the
  crown's self-occlusion (a white-sky render divided by the albedo).

So the cards carry no baked lighting: the scene's sun and sky light them
through the real leaves' normals. cards.json records each card's proportions.
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
VERDANT = os.path.join(os.path.dirname(ROOT), "verdant")
sys.path.insert(0, VERDANT)

import bpy  # noqa: E402
import render_gpu  # noqa: E402
import numpy as np  # noqa: E402
import verdant  # noqa: E402

verdant.register()
from verdant import catalog  # noqa: E402

OUT = os.path.join(ROOT, "summit", "cards")

# card name: (Verdant species, variant, season)
CARDS = {
    "SPRUCE_A": ("SPRUCE", 0, "SUMMER"), "SPRUCE_B": ("SPRUCE", 1, "SUMMER"), "SPRUCE_C": ("SPRUCE", 2, "SUMMER"),
    "PINE_A": ("PINE", 0, "SUMMER"), "PINE_B": ("PINE", 1, "SUMMER"),
    "OAK_A": ("OAK", 0, "SUMMER"), "OAK_B": ("OAK", 1, "SUMMER"),
    "MAPLE_A": ("MAPLE", 0, "SUMMER"), "MAPLE_B": ("MAPLE", 2, "SUMMER"),
    "BIRCH_A": ("BIRCH", 0, "SUMMER"), "BIRCH_B": ("BIRCH", 1, "SUMMER"),
    "SHRUB_A": ("SHRUB", 0, "SUMMER"), "SHRUB_B": ("SHRUB", 1, "SUMMER"),
    "MAPLE_AUTUMN_A": ("MAPLE", 0, "AUTUMN"), "MAPLE_AUTUMN_B": ("MAPLE", 1, "AUTUMN"),
    "OAK_AUTUMN": ("OAK", 2, "AUTUMN"), "BIRCH_AUTUMN": ("BIRCH", 2, "AUTUMN"),
}

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
HEIGHT = 512
SAMPLES = 96
names = []
i = 0
while i < len(argv):
    if argv[i] == "--height":
        HEIGHT = int(argv[i + 1])
        i += 2
    elif argv[i] == "--samples":
        SAMPLES = int(argv[i + 1])
        i += 2
    else:
        names.append(argv[i].upper())
        i += 1


def reset(season):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.verdant.season = season
    sc.render.engine = "CYCLES"
    render_gpu.enable(sc)
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.cycles.transparent_max_bounces = 32
    sc.render.film_transparent = True
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    # a white sky of strength 1 renders each surface at its albedo times its occlusion
    world = bpy.data.worlds.new("bake")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    vl = sc.view_layers[0]
    vl.use_pass_diffuse_color = True
    vl.use_pass_normal = True
    # the passes reach disk through the compositor, one float EXR each (Blender 5.2's multilayer
    # writer only keeps the combined image)
    tree = bpy.data.node_groups.new("bake", "CompositorNodeTree")
    sc.compositing_node_group = tree
    rl = tree.nodes.new("CompositorNodeRLayers")
    fo = tree.nodes.new("CompositorNodeOutputFile")
    fo.format.media_type = "IMAGE"
    fo.format.file_format = "OPEN_EXR"
    fo.format.color_depth = "32"
    fo.directory = bpy.app.tempdir
    fo.file_name = "card_"
    for name, key, kind in PASSES:
        fo.file_output_items.new(kind, name)
        tree.links.new(rl.outputs[key], fo.inputs[name])
    return sc


def bounds(coll):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in coll.all_objects:
        if o.type != "MESH" or o.hide_render:
            continue
        me = o.evaluated_get(dg).data
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        pts.append(co.reshape(-1, 3))
    p = np.concatenate(pts)
    return p.min(0), p.max(0)


# file name suffix, Render Layers output, socket type
PASSES = (("Combined", "Image", "RGBA"), ("DiffCol", "Diffuse Color", "RGBA"), ("Normal", "Normal", "VECTOR"))


def _passes():
    """{pass name: (h, w, channels)} from the last render, rows bottom-up like Blender images."""
    import OpenImageIO as oiio

    out = {}
    for name, _key, _kind in PASSES:
        inp = oiio.ImageInput.open(os.path.join(bpy.app.tempdir, f"card_{name}.exr"))
        spec = inp.spec()
        out[name] = inp.read_image(0, 0, 0, spec.nchannels, oiio.FLOAT)[::-1]
        inp.close()
    return {"Combined": out["Combined"][..., :4], "DiffCol": out["DiffCol"][..., :3], "Normal": out["Normal"][..., :3]}


def render(sc, cam, loc, rot, scale, w, h, frame):
    """Render one view. frame: the card's (along, up, toward viewer) axes in world space.

    Returns (albedo + alpha, card-space normal + occlusion), both (h, w, 4)."""
    cam.location = loc
    cam.rotation_euler = rot
    cam.data.ortho_scale = scale
    sc.render.resolution_x, sc.render.resolution_y = w, h
    bpy.ops.render.render()
    p = _passes()
    alpha = np.clip(p["Combined"][..., 3], 0.0, 1.0)
    cover = np.maximum(alpha, 1e-4)[..., None]
    albedo = np.clip(p["DiffCol"] / cover, 0.0, 1.0)          # the passes are premultiplied by coverage
    lit = p["Combined"][..., :3] / cover
    occl = np.clip((lit / np.maximum(albedo, 0.02)).mean(-1), 0.0, 1.0)
    n = p["Normal"] / cover
    n = np.stack([n @ np.asarray(axis, np.float32) for axis in frame], -1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    return (np.concatenate([albedo, alpha[..., None]], -1),
            np.concatenate([n * 0.5 + 0.5, occl[..., None]], -1))


def bleed(a, steps=4):
    """Spread colour into transparent pixels so filtering never pulls in a dark fringe."""
    rgb, alpha = a[..., :3].copy(), a[..., 3]
    known = alpha > 0.02
    for _ in range(steps):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(alpha.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        grow = ~known & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        known = known | grow
    # the rest gets one flat colour, which compresses to almost nothing
    rgb[~known] = rgb[alpha > 0.5].mean(0) if (alpha > 0.5).any() else 0.0
    return np.concatenate([rgb, alpha[..., None]], -1)


def srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def save_png(name, rgba):
    """Write an (h, w, 4) array as it is (no colour management) to summit/cards/<name>.png."""
    h, w, _ = rgba.shape
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(np.ascontiguousarray(rgba, np.float32).ravel())
    img.filepath_raw = os.path.join(OUT, name + ".png")
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def bake(name, sp_id, variant, season):
    sc = reset(season)
    coll = catalog.variant_collection(sp_id, variant)
    catalog.apply_season(coll.objects, season)
    sc.collection.children.link(coll)
    lo, hi = bounds(coll)
    height = float(hi[2])
    half = float(max(abs(lo[0]), abs(hi[0]), abs(lo[1]), abs(hi[1]))) * 1.03
    width = half * 2.0
    tall = height * 1.03  # a little headroom above the crown
    hp = HEIGHT if tall >= width else int(HEIGHT * tall / width)
    wp = int(round(hp * width / tall / 4.0)) * 4
    cell = max(hp, wp)
    # exact extents the images cover, with the image bottom at the tree's base
    span_z = max(tall, width) * (hp / max(hp, wp))
    span_x = max(tall, width) * (wp / max(hp, wp))

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    cam.data.clip_end = 1000.0
    sc.collection.objects.link(cam)
    sc.camera = cam
    dist = 200.0
    zc = span_z * 0.5
    fit = max(tall, width)  # ortho scale spans the larger image side
    # each view's card axes (along, up, toward the viewer), matching trees._card_mesh
    front = render(sc, cam, (0.0, -dist, zc), (math.pi / 2, 0.0, 0.0), fit, wp, hp,
                   ((1, 0, 0), (0, 0, 1), (0, -1, 0)))
    side = render(sc, cam, (dist, 0.0, zc), (math.pi / 2, 0.0, math.pi / 2), fit, wp, hp,
                  ((0, 1, 0), (0, 0, 1), (1, 0, 0)))
    top = render(sc, cam, (0.0, 0.0, height + dist), (0.0, 0.0, 0.0), span_x, wp, wp,
                 ((1, 0, 0), (0, 1, 0), (0, 0, 1)))

    def atlas(k):
        a = np.zeros((cell, wp * 3, 4), np.float32)
        a[:hp, :wp] = front[k]
        a[:hp, wp:2 * wp] = side[k]
        a[:wp, 2 * wp:] = top[k]
        return a

    colour = atlas(0)
    cover = colour[..., 3:]
    normal = atlas(1)
    # spread colours, normals and occlusion past the silhouette, so filtering pulls in no dark fringe
    colour = bleed(colour)
    colour[..., :3] = srgb(colour[..., :3])
    occl = bleed(np.concatenate([np.repeat(normal[..., 3:], 3, -1), cover], -1))[..., :1]
    normal = np.concatenate([bleed(np.concatenate([normal[..., :3], cover], -1))[..., :3], occl], -1)
    save_png(name, colour)
    save_png(name + "_N", normal)
    lit = colour[..., 3] > 0.5
    print(f"  albedo (sRGB) {colour[..., :3][lit].mean(0).round(3)}  occlusion {occl[..., 0][lit].mean():.2f}")

    print(f"{name}: {wp * 3}x{cell}  height {height:.1f} m  width {width:.1f} m")
    return {"width": span_x / height, "tall": span_z / height, "side_v": hp / cell, "top_v": wp / cell,
            "height": height, "species": sp_id, "season": season}


def main():
    os.makedirs(OUT, exist_ok=True)
    meta_path = os.path.join(OUT, "cards.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    for name, (sp, v, season) in CARDS.items():
        if names and name not in names:
            continue
        meta[name] = bake(name, sp, v, season)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    print("wrote", meta_path)


main()
