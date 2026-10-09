# SPDX-License-Identifier: GPL-3.0-or-later
"""Forest layers: a geometry-nodes modifier that grows impostor trees on a terrain.

Each layer is one ``SM Forest`` modifier, so a terrain can carry broadleaf
woods low down and firs up to the tree line. Trees follow the baked
``sm_forest`` attribute (gentle, sheltered ground, natural clumps), thin
out and shrink toward the tree line, stay off steep faces and out of the
water. Instances are never realised, so even dense forests stay light.
"""

import math

import bpy

from .nodekit import NB, arrange, find, new_socket

GROUP = "SM Forest"
GROUP_VERSION = 1

# name, socket type, default, min, max, subtype, description
INPUTS = [
    ("Collection", "NodeSocketCollection", None, None, None, None, "Trees to grow; each child is a variant"),
    ("Density", "NodeSocketFloat", 200.0, 0.0, 100000.0, None, "Trees per hectare on ideal ground"),
    ("Viewport Amount", "NodeSocketFloat", 0.3, 0.0, 1.0, "FACTOR", "Share of trees shown in the viewport"),
    ("Seed", "NodeSocketInt", 0, 0, 100000, None, "Random seed"),
    ("Tree Height", "NodeSocketFloat", 16.0, 0.01, 200.0, "DISTANCE", "Average tree height"),
    ("Height Random", "NodeSocketFloat", 0.35, 0.0, 1.0, "FACTOR", "Random height variation"),
    ("Tree Line", "NodeSocketFloat", 0.5, -1.0, 2.0, None, "Highest trees, as a fraction of the terrain height"),
    ("Lowest", "NodeSocketFloat", 0.0, -1.0, 2.0, None, "Lowest trees, as a fraction of the terrain height"),
    ("Max Slope", "NodeSocketFloat", math.radians(35.0), 0.0, math.pi / 2, "ANGLE", "No trees on steeper ground"),
    ("Min Distance", "NodeSocketFloat", 2.5, 0.0, 100.0, "DISTANCE", "Minimum spacing between trees"),
    ("Clumping", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "Gather trees into groves instead of spreading them"),
    ("Shrink at Tree Line", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "Trees get smaller near the tree line"),
    ("Terrain Height", "NodeSocketFloat", 1000.0, 0.01, 100000.0, "DISTANCE", "Height of the terrain's highest peak"),
    ("Mask", "NodeSocketString", "sm_forest", None, None, None, "Float attribute or vertex group that guides trees"),
]
INPUT_NAMES = [i[0] for i in INPUTS]


def _build(tree):
    tree.nodes.clear()
    tree.interface.clear()
    new_socket(tree, "Geometry", "INPUT", "NodeSocketGeometry")
    for name, stype, default, lo, hi, subtype, desc in INPUTS:
        new_socket(tree, name, "INPUT", stype, default, lo, hi, subtype, desc)
    new_socket(tree, "Geometry", "OUTPUT", "NodeSocketGeometry")

    b = NB(tree)
    gi = b.node("NodeGroupInput")
    go = b.node("NodeGroupOutput")
    I = {s.name: s for s in gi.outputs if s.name}  # noqa: E741

    pos = b.node("GeometryNodeInputPosition")
    _x, _y, z = b.sep(b.out(pos))
    h = b.math("DIVIDE", z, I["Terrain Height"])
    top = I["Tree Line"]
    alt = b.mul(b.inv(b.smooth(h, b.sub(top, 0.1), top)), b.smooth(h, I["Lowest"], b.add(I["Lowest"], 0.015)))

    attr = b.node("GeometryNodeInputNamedAttribute", {"Name": I["Mask"]}, data_type="FLOAT")
    clumped = b.math("POWER", b.math("MAXIMUM", b.out(attr, "Attribute"), 0.0), b.add(0.6, b.mul(I["Clumping"], 2.4)))
    mask = b.node("GeometryNodeSwitch", {"Switch": b.out(attr, "Exists"), "False": 1.0, "True": clumped},
                  input_type="FLOAT")

    nrm = b.node("GeometryNodeInputNormal")
    _nx, _ny, nz = b.sep(b.out(nrm, "Normal"))
    cos_s = b.math("COSINE", I["Max Slope"])
    flat = b.smooth(nz, b.sub(cos_s, 0.03), b.add(cos_s, 0.05))

    isvp = b.node("GeometryNodeIsViewport")
    vp = b.node("GeometryNodeSwitch", {"Switch": b.out(isvp), "False": 1.0, "True": I["Viewport Amount"]},
                input_type="FLOAT")
    factor = b.mul(b.mul(b.mul(alt, b.out(mask)), flat), b.out(vp))

    dist = b.node("GeometryNodeDistributePointsOnFaces", distribute_method="POISSON")
    b.links.new(I["Geometry"], find(dist.inputs, "Mesh"))
    b.links.new(I["Min Distance"], find(dist.inputs, "Distance Min"))
    b.links.new(b.math("DIVIDE", I["Density"], 10000.0), find(dist.inputs, "Density Max"))
    b.links.new(factor, find(dist.inputs, "Density Factor"))
    b.links.new(I["Seed"], find(dist.inputs, "Seed"))

    def rand(lo, hi, salt, dtype="FLOAT"):
        n = b.node("FunctionNodeRandomValue", data_type=dtype)
        b.set(find(n.inputs, "Min"), lo)
        b.set(find(n.inputs, "Max"), hi)
        b.set(find(n.inputs, "Seed"), b.add(I["Seed"], salt))
        return b.out(n)

    # trees are upright whatever the slope; only spin them
    spin = rand(0.0, 2.0 * math.pi, 11.0)
    euler = b.combine(0.0, 0.0, spin)
    # krummholz: smaller trees just below the tree line
    shrink = b.mul(I["Shrink at Tree Line"], b.smooth(h, b.sub(top, 0.18), top))
    hr = I["Height Random"]
    size = b.mul(b.mul(rand(b.inv(hr), b.add(1.0, hr), 23.0), I["Tree Height"]), b.inv(b.mul(shrink, 0.55)))

    info = b.node("GeometryNodeCollectionInfo", {"Collection": I["Collection"], "Separate Children": True,
                                                 "Reset Children": True}, transform_space="ORIGINAL")
    pick = b.node("FunctionNodeRandomValue", data_type="INT")
    b.set(find(pick.inputs, "Min"), 0)
    b.set(find(pick.inputs, "Max"), 100000)
    b.set(find(pick.inputs, "Seed"), I["Seed"])
    iop = b.node("GeometryNodeInstanceOnPoints", {"Pick Instance": True})
    b.links.new(find(dist.outputs, "Points"), find(iop.inputs, "Points"))
    b.links.new(b.out(info), find(iop.inputs, "Instance"))
    b.links.new(b.out(pick), find(iop.inputs, "Instance Index"))
    b.links.new(euler, find(iop.inputs, "Rotation"))
    b.links.new(size, find(iop.inputs, "Scale"))

    join = b.node("GeometryNodeJoinGeometry")
    b.links.new(I["Geometry"], join.inputs[0])
    b.links.new(b.out(iop), join.inputs[0])
    b.links.new(b.out(join), go.inputs[0])
    arrange(tree)
    tree["sm_version"] = GROUP_VERSION


def forest_group():
    g = bpy.data.node_groups.get(GROUP)
    if g is None or g.bl_idname != "GeometryNodeTree":
        g = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
        _build(g)
    return g


def input_ids(group=None):
    group = group or forest_group()
    return {it.name: it.identifier for it in group.interface.items_tree
            if it.item_type == "SOCKET" and it.in_out == "INPUT"}


def is_layer(mod):
    return mod.type == "NODES" and mod.node_group is not None and mod.node_group.name.startswith(GROUP)


def layers(obj):
    return [m for m in obj.modifiers if is_layer(m)]


def slot(mod, key):
    """(owner, property) holding a modifier input.

    Blender 5 keeps inputs in mod.properties.inputs.<id>.value; earlier
    versions store them as ID properties on the modifier itself.
    """
    ident = input_ids(mod.node_group)[key]
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        return getattr(props.inputs, ident), "value"
    return mod, f'["{ident}"]'


def get(mod, key):
    owner, prop = slot(mod, key)
    if prop.startswith("["):
        return owner[prop[2:-2]]
    return getattr(owner, prop)


def set_value(mod, key, value):
    owner, prop = slot(mod, key)
    if prop.startswith("["):
        owner[prop[2:-2]] = value
    else:
        setattr(owner, prop, value)
    mod.id_data.update_tag()


def draw_input(layout, mod, key, text=None):
    owner, prop = slot(mod, key)
    layout.prop(owner, prop, text=text if text is not None else key)


def add_layer(obj, collection, name, **values):
    """Add a forest layer to obj. values are keyed by forest input name."""
    group = forest_group()
    mod = obj.modifiers.new(name, "NODES")
    mod.node_group = group
    ids = input_ids(group)
    set_value(mod, "Collection", collection)
    set_value(mod, "Seed", (len(layers(obj)) - 1) * 131)
    for k, v in values.items():
        if k not in ids:
            raise KeyError(f"unknown forest input {k!r}")
        set_value(mod, k, v)
    return mod
