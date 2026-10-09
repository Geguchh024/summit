# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers for building shader and geometry node trees from Python.

Helpers take plain values or sockets and return a socket, so node graphs
read like expressions. ``arrange`` lays the finished tree out in columns
so it stays readable when someone opens it in the node editor.
"""

import bpy


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_color(h):
    h = h.lstrip("#")
    r, g, b = (srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))
    return (r, g, b, 1.0)


_ALIASES = {"Fac": "Factor", "Factor": "Fac"}


def available(sockets):
    return [s for s in sockets if not getattr(s, "is_unavailable", not getattr(s, "enabled", True))]


def find(sockets, key):
    av = available(sockets)
    if isinstance(key, int):
        return av[key]
    for name in (key, _ALIASES.get(key)):
        for s in av:
            if s.identifier == name or s.name == name:
                return s
    raise KeyError(key)


class NB:
    """Node builder for shader and geometry node trees."""

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links

    def node(self, idname, inputs=None, **props):
        n = self.nodes.new(idname)
        for k, v in props.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(find(n.inputs, k), v)
        return n

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.links.new(v, sock)
        elif v is not None:
            if isinstance(v, str):
                v = hex_color(v)
            if sock.type == "RGBA" and len(v) == 3:
                v = (*v, 1.0)
            sock.default_value = v

    @staticmethod
    def out(node, key=0):
        return find(node.outputs, key)

    def math(self, op, a, b=0.0, c=None, clamp=False):
        n = self.node("ShaderNodeMath", {0: a}, operation=op, use_clamp=clamp)
        ins = available(n.inputs)
        if len(ins) > 1:
            self.set(ins[1], b)
        if c is not None and len(ins) > 2:
            self.set(ins[2], c)
        return self.out(n)

    def add(self, a, b):
        return self.math("ADD", a, b)

    def mul(self, a, b, clamp=False):
        return self.math("MULTIPLY", a, b, clamp=clamp)

    def sub(self, a, b):
        return self.math("SUBTRACT", a, b)

    def inv(self, a):
        return self.math("SUBTRACT", 1.0, a)

    def vmath(self, op, a, b=(0.0, 0.0, 0.0), key=0, scale=None):
        n = self.node("ShaderNodeVectorMath", {0: a}, operation=op)
        ins = available(n.inputs)
        if len(ins) > 1 and ins[1].type == "VECTOR":
            self.set(ins[1], b)
        if scale is not None:
            self.set(find(n.inputs, "Scale"), scale)
        return self.out(n, key)

    def mix(self, fac, a, b, blend="MIX"):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_factor=True)
        self.set(find(n.inputs, "Factor_Float"), fac)
        self.set(find(n.inputs, "A_Color"), a)
        self.set(find(n.inputs, "B_Color"), b)
        return find(n.outputs, "Result_Color")

    def mixf(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
        self.set(find(n.inputs, "Factor_Float"), fac)
        self.set(find(n.inputs, "A_Float"), a)
        self.set(find(n.inputs, "B_Float"), b)
        return find(n.outputs, "Result_Float")

    def mixv(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="VECTOR", clamp_factor=True)
        self.set(find(n.inputs, "Factor_Float"), fac)
        self.set(find(n.inputs, "A_Vector"), a)
        self.set(find(n.inputs, "B_Vector"), b)
        return find(n.outputs, "Result_Vector")

    def smooth(self, x, lo, hi):
        """0 below lo, 1 above hi (or reversed when lo > hi), with a smooth ramp."""
        n = self.node("ShaderNodeMapRange", {"Value": x, "From Min": lo, "From Max": hi},
                      interpolation_type="SMOOTHSTEP")
        return self.out(n, "Result")

    def remap(self, x, lo, hi, a, b, clamp=True):
        n = self.node("ShaderNodeMapRange", {"Value": x, "From Min": lo, "From Max": hi, "To Min": a, "To Max": b},
                      clamp=clamp)
        return self.out(n, "Result")

    def sep(self, vec):
        n = self.node("ShaderNodeSeparateXYZ", {0: vec})
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def combine(self, x, y, z):
        return self.out(self.node("ShaderNodeCombineXYZ", {"X": x, "Y": y, "Z": z}))

    def noise(self, vec, scale, detail=4.0, rough=0.5, key="Fac", dims="3D", w=None, distortion=0.0):
        inputs = {"Vector": vec, "Scale": scale, "Detail": detail, "Roughness": rough, "Distortion": distortion}
        if w is not None:
            inputs["W"] = w
        if dims == "1D":
            inputs.pop("Vector")
        return self.out(self.node("ShaderNodeTexNoise", inputs, noise_dimensions=dims), key)

    def voronoi(self, vec, scale, feature="F1", key="Distance", rand=1.0):
        return self.out(self.node("ShaderNodeTexVoronoi", {"Vector": vec, "Scale": scale, "Randomness": rand},
                                  feature=feature), key)

    def hsv(self, color, hue=0.5, sat=1.0, val=1.0):
        return self.out(self.node("ShaderNodeHueSaturation", {"Color": color, "Hue": hue, "Saturation": sat,
                                                              "Value": val}))

    def bump(self, height, strength=0.4, distance=0.1, normal=None):
        inputs = {"Height": height, "Strength": strength, "Distance": distance}
        if normal is not None:
            inputs["Normal"] = normal
        return self.out(self.node("ShaderNodeBump", inputs))

    def attr(self, name, key="Fac"):
        return self.out(self.node("ShaderNodeAttribute", attribute_name=name), key)


def new_socket(tree, name, in_out, stype, default=None, lo=None, hi=None, subtype=None, desc=""):
    s = tree.interface.new_socket(name, in_out=in_out, socket_type=stype)
    if desc:
        s.description = desc
    if subtype and hasattr(s, "subtype"):
        s.subtype = subtype
    if default is not None and hasattr(s, "default_value"):
        if stype == "NodeSocketColor" and isinstance(default, str):
            default = hex_color(default)
        s.default_value = default
    if lo is not None and hasattr(s, "min_value"):
        s.min_value, s.max_value = lo, hi
    return s


def arrange(tree, dx=230, dy=190):
    """Lay nodes out in columns by their distance from the output node(s)."""
    nodes = list(tree.nodes)
    feeds = {n: [] for n in nodes}   # node -> nodes it feeds
    for link in tree.links:
        feeds[link.from_node].append(link.to_node)
    depth = {}

    def walk(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen:
            return 0
        d = 0 if not feeds[n] else 1 + max(walk(m, seen + (n,)) for m in feeds[n])
        depth[n] = d
        return d

    for n in nodes:
        walk(n)
    columns = {}
    for n in nodes:
        columns.setdefault(depth[n], []).append(n)
    for d, col in columns.items():
        for i, n in enumerate(col):
            n.location = (-d * dx, (len(col) * 0.5 - i) * dy)
