# SPDX-License-Identifier: GPL-3.0-or-later
"""Impostor trees: image cards of Verdant's procedural trees, light enough for whole mountainsides.

Each card shows one real tree, rendered by tools/bake_tree_cards.py from
the front, the side and above: its albedo (cards/<NAME>.png) and its
leaves' normals with the crown's self-occlusion (cards/<NAME>_N.png). In
the scene a tree is two crossed vertical planes plus one horizontal plane
at crown height: 12 triangles, so a forest of hundreds of thousands of
trees stays light. The cards hold no lighting of their own: the scene's
sun and sky light every leaf through its baked normal, so a forest reacts
to the time of day like real trees. The images are packed into the
.blend, so files render without the add-on. Each instance gets a slightly
different tint.

Cards are 1 m tall; forest layers scale them to the real tree height.

    Summit Library          (fake user, never linked to a scene)
      SM Fir                one collection per species
        SM Fir A            one card object per tree image
"""

import json
import os

import bpy

from . import haze, nodekit
from .nodekit import NB

LIBRARY = "Summit Library"
CARD_DIR = os.path.join(os.path.dirname(__file__), "cards")

# cards: tree images; crown: height of the canopy plane (fraction of the tree height)
SPECIES = {
    "FIR": dict(label="Fir", cards=("SPRUCE_A", "SPRUCE_B", "SPRUCE_C"), crown=0.35),
    "PINE": dict(label="Pine", cards=("PINE_A", "PINE_B"), crown=0.75),
    "BROADLEAF": dict(label="Broadleaf", cards=("OAK_A", "OAK_B", "MAPLE_A", "MAPLE_B", "BIRCH_A", "BIRCH_B"),
                      crown=0.6),
    "AUTUMN": dict(label="Autumn Broadleaf", cards=("MAPLE_AUTUMN_A", "MAPLE_AUTUMN_B", "OAK_AUTUMN",
                                                    "BIRCH_AUTUMN"), crown=0.6),
    "SHRUB": dict(label="Shrub", cards=("SHRUB_A", "SHRUB_B"), crown=0.5),
}

_meta = None


def card_info(name):
    global _meta
    if _meta is None:
        with open(os.path.join(CARD_DIR, "cards.json"), encoding="utf-8") as f:
            _meta = json.load(f)
    return _meta[name]


def library():
    lib = bpy.data.collections.get(LIBRARY)
    if lib is None:
        lib = bpy.data.collections.new(LIBRARY)
        lib.use_fake_user = True
        lib["sm_library"] = True
    return lib


def _card_mesh(name, info, crown):
    w = info["width"] * 0.5
    t = info["tall"]
    sv, tv = info["side_v"], info["top_v"]
    third = 1.0 / 3.0
    verts = [(-w, 0, 0), (w, 0, 0), (w, 0, t), (-w, 0, t),          # front, seen from -Y
             (0, -w, 0), (0, w, 0), (0, w, t), (0, -w, t),          # side, seen from +X
             (-w, -w, crown), (w, -w, crown), (w, w, crown), (-w, w, crown)]  # canopy, seen from above
    uvs = [(0, 0), (third, 0), (third, sv), (0, sv),
           (third, 0), (2 * third, 0), (2 * third, sv), (third, sv),
           (2 * third, 0), (1, 0), (1, tv), (2 * third, tv)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11)])
    layer = me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", [c for uv in uvs for c in uv])
    me.update()
    return me


def _image(name, data=False):
    key = f"SM Card {name}"
    img = bpy.data.images.get(key)
    if img is None:
        img = bpy.data.images.load(os.path.join(CARD_DIR, name + ".png"), check_existing=False)
        img.name = key
        if data:
            img.colorspace_settings.name = "Non-Color"
            img.alpha_mode = "CHANNEL_PACKED"
        else:
            img.alpha_mode = "STRAIGHT"
        img.pack()
    return img


def card_material(name, crown):
    key = f"SM Card {name.title().replace('_', ' ')}"
    mat = bpy.data.materials.get(key)
    if mat:
        return mat
    mat = bpy.data.materials.new(key)
    mat.use_nodes = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = False
    tree = mat.node_tree
    tree.nodes.clear()
    b = NB(tree)
    tc = b.node("ShaderNodeTexCoord")
    uv = b.out(tc, "UV")
    tex = b.node("ShaderNodeTexImage", {"Vector": uv}, image=_image(name), interpolation="Linear",
                 extension="CLIP")
    ntex = b.node("ShaderNodeTexImage", {"Vector": uv}, image=_image(name + "_N", data=True),
                  interpolation="Linear", extension="CLIP")
    r = b.out(b.node("ShaderNodeObjectInfo"), "Random")
    geom = b.node("ShaderNodeNewGeometry")
    # every tree a little different: lighter, darker, warmer or cooler; darker inside the crown.
    # Lifted above the true leaf albedo: real canopies glow with translucency and sheen, never black
    occl = b.out(ntex, "Alpha")
    col = b.hsv(b.out(tex, "Color"), hue=b.add(0.485, b.mul(r, 0.03)), sat=b.add(0.9, b.mul(r, 0.25)),
                val=b.add(1.3, b.mul(r, 0.4)))
    occf = b.add(0.55, b.mul(occl, 0.45))
    col = b.mix(1.0, col, b.combine(occf, occf, occf), blend="MULTIPLY")
    # the leaves' own normals, from the card's frame (along, up, toward the viewer) to object space;
    # seen from behind, "toward the viewer" flips
    u, _v, _w = b.sep(uv)
    side = b.mul(b.math("GREATER_THAN", u, 0.3333), b.math("LESS_THAN", u, 0.6667))
    top = b.math("GREATER_THAN", u, 0.6667)
    t_axis = b.mixv(side, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    b_axis = b.mixv(top, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
    n_axis = b.mixv(top, b.mixv(side, (0.0, -1.0, 0.0), (1.0, 0.0, 0.0)), (0.0, 0.0, 1.0))
    facing = b.math("SUBTRACT", 1.0, b.mul(b.out(geom, "Backfacing"), 2.0))
    nx, ny, nz = b.sep(b.vmath("SUBTRACT", b.vmath("SCALE", b.out(ntex, "Color"), scale=2.0), (1.0, 1.0, 1.0)))
    leaf = b.vmath("ADD", b.vmath("ADD", b.vmath("SCALE", t_axis, scale=nx), b.vmath("SCALE", b_axis, scale=ny)),
                   b.vmath("SCALE", n_axis, scale=b.mul(nz, facing)))
    # plus a little of a normal pointing away from the crown centre, so the crown shades as one volume
    ox, oy, oz = b.sep(b.out(tc, "Object"))
    sph = b.vmath("NORMALIZE", b.combine(ox, oy, b.mul(b.sub(oz, crown), 0.8)))
    obj_n = b.vmath("NORMALIZE", b.mixv(0.3, b.vmath("NORMALIZE", leaf), sph))
    nrm = b.out(b.node("ShaderNodeVectorTransform", {"Vector": obj_n}, vector_type="NORMAL",
                       convert_from="OBJECT", convert_to="WORLD"))
    diff = b.node("ShaderNodeBsdfDiffuse", {"Color": col, "Normal": nrm})
    # sunlight shining through the leaves
    trans = b.node("ShaderNodeBsdfTranslucent", {"Color": b.hsv(col, sat=1.2, val=1.3),
                                                 "Normal": nrm})
    leafy = b.node("ShaderNodeMixShader", {0: 0.3, 1: b.out(diff), 2: b.out(trans)})
    clear = b.node("ShaderNodeBsdfTransparent")
    # a hard cut-out: no half-transparent fringes to pile up in dense forests
    alpha = b.math("GREATER_THAN", b.out(tex, "Alpha"), 0.5)
    # a plane seen edge-on is only a streak: fade it out, the crossing plane shows the tree
    edge_on = b.math("ABSOLUTE", b.vmath("DOT_PRODUCT", b.out(geom, "Incoming"), b.out(geom, "Normal"), key="Value"))
    alpha = b.mul(alpha, b.smooth(edge_on, 0.06, 0.2))
    # shadows: real crowns let light through, opaque cards would black out a dense forest.
    # The canopy plane casts none (it would shade its own tree); the upright planes cast 45 %.
    canopy = top
    shadow = b.out(b.node("ShaderNodeLightPath"), "Is Shadow Ray")
    shadow_opacity = b.mixf(canopy, 0.45, 0.0)
    alpha = b.mul(alpha, b.mixf(shadow, 1.0, shadow_opacity))
    final = b.node("ShaderNodeMixShader", {0: alpha, 1: b.out(clear), 2: haze.mix(b, b.out(leafy))})
    out = b.node("ShaderNodeOutputMaterial")
    b.links.new(b.out(final), out.inputs["Surface"])
    nodekit.arrange(tree)
    return mat


def species_collection(sp):
    """The species collection, with a card object for every tree image."""
    info = SPECIES[sp]
    name = f"SM {info['label']}"
    lib = library()
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        coll["sm_species"] = sp
    if coll.name not in lib.children:
        lib.children.link(coll)
    if not coll.objects:
        for i, card in enumerate(info["cards"]):
            vname = f"{name} {chr(ord('A') + i)}"
            me = _card_mesh(vname, card_info(card), info["crown"])
            me.materials.append(card_material(card, info["crown"]))
            obj = bpy.data.objects.new(vname, me)
            obj["sm_species"] = sp
            coll.objects.link(obj)
    return coll
