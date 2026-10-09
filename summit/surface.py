# SPDX-License-Identifier: GPL-3.0-or-later
"""Terrain and water shaders.

Every terrain material is a thin wrapper around one shared node group,
``SM Terrain Surface``. The wrapper feeds it the terrain's own baked maps
(normal map, plus a mask image: flow, sediment, cavity and forest), and the
group turns them into rock, scree, ground cover, forest floor, beach and
snow. Biomes are just different input values on the group node.

Far away the baked maps carry the look: erosion channels, scree fans and
snow-filled gullies stay sharp on a light mesh. Up close, 3D procedural
rock detail fades in (strata, cracks, grain), so close-ups hold up too
without stretching on cliffs.
"""

import math

import bpy

from . import biomes, haze, nodekit
from .nodekit import NB, find, new_socket

GROUP = "SM Terrain Surface"
GROUP_VERSION = 2

# name, socket type, default, min, max, subtype, description
MAP_INPUTS = [
    ("Normal", "NodeSocketVector", None, None, None, None, "Terrain normal (from the baked normal map)"),
    ("Flow", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR", "Erosion channels, from the mask map"),
    ("Sediment", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR", "Settled scree and sediment, from the mask map"),
    ("Cavity", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "0.5 flat, high in gullies, low on ridges"),
    ("Forest", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR", "Where trees grow, from the mask map"),
    ("Occlusion", "NodeSocketFloat", 1.0, 0.0, 1.0, "FACTOR", "Baked sky visibility, from the normal map's alpha"),
    ("Terrain Height", "NodeSocketFloat", 1000.0, 0.01, 100000.0, "DISTANCE", "Height of the highest peak"),
]
BIOME_INPUTS = [
    ("Rock Color", "NodeSocketColor", "#7f7a73", None, None, None, "Main rock colour"),
    ("Rock Color 2", "NodeSocketColor", "#9e978d", None, None, None, "Second rock colour, mixed in patches and strata"),
    ("Rock Streaks", "NodeSocketColor", "#4b4641", None, None, None, "Water stains down cliffs and erosion channels"),
    ("Strata", "NodeSocketFloat", 0.15, 0.0, 1.0, "FACTOR", "Visible horizontal rock layers"),
    ("Strata Scale", "NodeSocketFloat", 22.0, 0.1, 1000.0, "DISTANCE", "Thickness of the rock layers"),
    ("Cracks", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "Fracture lines in the rock, seen up close"),
    ("Scree Color", "NodeSocketColor", "#8e887f", None, None, None, "Loose stones and sediment"),
    ("Ground Color", "NodeSocketColor", "#56692f", None, None, None, "Grass, moss or sand on gentle slopes"),
    ("Ground Color 2", "NodeSocketColor", "#7c8443", None, None, None, "Second ground colour, mixed in patches"),
    ("Dry Color", "NodeSocketColor", "#9a8d5c", None, None, None, "Dry ground on ridges and toward the ground line"),
    ("Ground Line", "NodeSocketFloat", 0.55, -1.0, 2.0, None, "Ground cover stops at this fraction of the height"),
    ("Ground Max Slope", "NodeSocketFloat", math.radians(32.0), 0.0, math.pi / 2, "ANGLE",
     "Steeper slopes stay bare rock"),
    ("Forest Color", "NodeSocketColor", "#2b3a20", None, None, None, "Forest floor and canopy tint seen from afar"),
    ("Forest Line", "NodeSocketFloat", 0.45, -1.0, 2.0, None, "Tree line, as a fraction of the height"),
    ("Snow Color", "NodeSocketColor", "#eef2f8", None, None, None, "Snow colour"),
    ("Snow Line", "NodeSocketFloat", 0.65, -1.0, 2.0, None, "Snow starts at this fraction of the height"),
    ("Snow Amount", "NodeSocketFloat", 1.0, 0.0, 2.0, None, "Above 1 snow also reaches further down"),
    ("Snow Max Slope", "NodeSocketFloat", math.radians(52.0), 0.0, math.pi / 2, "ANGLE",
     "Snow does not stick to steeper faces"),
    ("Snow Dusting", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR",
     "Fresh snow on ledges and in couloirs below the snowline, drawing the rock structure"),
    ("Boulders", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "Rocks scattered through the ground cover"),
    ("Beach Color", "NodeSocketColor", "#b9a888", None, None, None, "Shore band just above the water"),
    ("Ripples", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR", "Wind ripples in sand, seen up close"),
    ("Macro Variation", "NodeSocketFloat", 0.5, 0.0, 1.0, "FACTOR", "Large-scale tone variation across the terrain"),
]
EXTRA_INPUTS = [
    ("Water Level", "NodeSocketFloat", -1.0, -1.0, 1.0, None, "Fraction of the height; -1 for no water"),
    ("Detail Scale", "NodeSocketFloat", 3.0, 0.01, 100.0, "DISTANCE", "Size of the close-up rock detail"),
    ("Detail Strength", "NodeSocketFloat", 0.7, 0.0, 4.0, None, "Bump strength of the close-up detail"),
    ("Detail Distance", "NodeSocketFloat", 350.0, 1.0, 100000.0, "DISTANCE",
     "Close-up detail fades out by this distance from the camera"),
    ("Haze", "NodeSocketFloat", 1.0, 0.0, 10.0, None,
     "How much of the scene's aerial haze this terrain gets (set in Summit's Haze panel)"),
    ("Occlusion Strength", "NodeSocketFloat", 0.8, 0.0, 1.0, "FACTOR",
     "How much the baked occlusion darkens gullies and the feet of walls"),
]
INPUTS = MAP_INPUTS + BIOME_INPUTS + EXTRA_INPUTS
ANGLE_INPUTS = {i[0] for i in INPUTS if i[5] == "ANGLE"}


def _build(tree):
    tree.nodes.clear()
    tree.interface.clear()
    for name, stype, default, lo, hi, subtype, desc in INPUTS:
        s = new_socket(tree, name, "INPUT", stype, default, lo, hi, subtype, desc)
        if name == "Normal":
            s.hide_value = True
    new_socket(tree, "Surface", "OUTPUT", "NodeSocketShader")
    for name, desc in (("Snow", "Snow cover mask"), ("Rock", "Bare rock mask"), ("Ground", "Ground cover mask")):
        new_socket(tree, name, "OUTPUT", "NodeSocketFloat", desc=desc)

    b = NB(tree)
    gi = b.node("NodeGroupInput")
    go = b.node("NodeGroupOutput")
    I = {s.name: s for s in gi.outputs if s.name}  # noqa: E741

    tc = b.node("ShaderNodeTexCoord")
    P = b.out(tc, "Object")
    px, py, pz = b.sep(P)
    h = b.math("DIVIDE", pz, I["Terrain Height"])
    geo = b.node("ShaderNodeNewGeometry")
    # surroundings (the apron around a terrain) have no baked maps: geometry normal and neutral masks
    apron = b.attr("sm_apron")
    keep = b.inv(apron)
    N = b.vmath("NORMALIZE", b.mixv(apron, I["Normal"], b.out(geo, "Normal")))
    flow = b.mul(I["Flow"], keep)
    sed = b.mul(I["Sediment"], keep)
    cav = b.mixf(apron, I["Cavity"], 0.5)
    forest_m = b.mixf(apron, I["Forest"], b.attr("sm_forest"))
    ao = b.mixf(apron, I["Occlusion"], 1.0)
    _nx, _ny, nz_fine = b.sep(N)
    # cover (grass, snow, scree) follows the broad slope; per-pixel rock detail would only speckle it
    _gx, _gy, nz_mesh = b.sep(b.out(geo, "Normal"))
    nz = b.mixf(0.35, nz_mesh, nz_fine)
    dist = b.out(b.node("ShaderNodeCameraData"), "View Distance")
    near = b.inv(b.smooth(dist, b.mul(I["Detail Distance"], 0.25), I["Detail Distance"]))
    mid = b.inv(b.smooth(dist, I["Detail Distance"], b.mul(I["Detail Distance"], 8.0)))
    ds = I["Detail Scale"]
    inv_ds = b.math("DIVIDE", 1.0, ds)
    steep = b.inv(b.smooth(nz_fine, 0.35, 0.8))

    # -- rock --------------------------------------------------------------
    macro = b.noise(P, 0.0025, detail=3.0, rough=0.55)
    patch = b.noise(P, 0.02, detail=6.0, rough=0.6)
    rock = b.mix(b.smooth(patch, 0.35, 0.68), I["Rock Color"], I["Rock Color 2"])
    warp = b.mul(b.noise(P, 0.004, detail=3.0), 3.0)
    band_w = b.add(b.math("DIVIDE", pz, I["Strata Scale"]), warp)
    band = b.noise(None, 1.0, detail=4.0, rough=0.6, dims="1D", w=band_w)
    strata_col = b.mix(b.smooth(band, 0.32, 0.68), I["Rock Color"], I["Rock Color 2"])
    strata_col = b.mix(b.mul(b.smooth(band, 0.64, 0.72), 0.45), strata_col, I["Rock Streaks"])
    # layers show on the cliff bands; benches and talus between them are muted, like a canyon's layer cake
    rock = b.mix(b.mul(I["Strata"], b.add(0.35, b.mul(steep, 0.65))), rock, strata_col)
    talus = b.mul(b.inv(steep), b.mul(I["Strata"], 0.7))
    rock = b.mix(talus, rock, b.mix(0.55, b.hsv(rock, sat=0.6), I["Scree Color"]))
    # large-scale light and dark areas
    tone = b.remap(macro, 0.3, 0.7, 0.0, 1.0)
    rock = b.mix(b.mul(I["Macro Variation"], 0.5), rock, b.mix(tone, b.hsv(rock, val=0.75), b.hsv(rock, val=1.2)))
    # water stains: along erosion channels, and vertical fluting down steep faces
    vstreak = b.noise(b.vmath("MULTIPLY", P, (1.0, 1.0, 0.07)), 0.06, detail=5.0)
    flute = b.noise(b.vmath("MULTIPLY", P, (1.0, 1.0, 0.04)), 0.35, detail=3.0)
    stain = b.add(b.mul(flow, 0.6), b.mul(b.mul(b.smooth(vstreak, 0.52, 0.72), steep), 0.5))
    rock = b.mix(b.math("MINIMUM", stain, 0.8), rock, I["Rock Streaks"])
    rock = b.mix(b.mul(steep, 0.35), rock, b.mix(flute, b.hsv(rock, val=0.82), b.hsv(rock, val=1.12)))
    # fractures: warped, stretched into vertical joints, and only in patches, so they never tile
    jitter = b.vmath("SCALE", b.vmath("SUBTRACT", b.noise(P, b.mul(inv_ds, 0.25), detail=3.0, key="Color"),
                                      (0.5, 0.5, 0.5)), scale=b.mul(ds, 2.5))
    joint_p = b.vmath("MULTIPLY", b.vmath("ADD", P, jitter), (1.0, 1.0, 0.45))
    crack_d = b.voronoi(joint_p, b.mul(inv_ds, 0.2), feature="DISTANCE_TO_EDGE", rand=0.9)
    crack_patch = b.smooth(b.noise(P, b.mul(inv_ds, 0.06), detail=3.0), 0.45, 0.62)
    crack = b.mul(b.inv(b.smooth(crack_d, 0.0, 0.035)), crack_patch)
    crack_f = b.mul(b.mul(crack, I["Cracks"]), b.mul(b.add(near, b.mul(mid, 0.3)), 0.55))
    rock = b.mix(crack_f, rock, b.hsv(I["Rock Streaks"], val=0.6))

    # -- scree: fresh broken rock, paler than the wall above it --------------
    gravel = b.voronoi(P, b.mul(inv_ds, 2.0), feature="F1", key="Color")
    gravel_v = b.out(b.node("ShaderNodeSeparateColor", {"Color": gravel}), 0)
    scree_col = b.mix(b.mul(gravel_v, 0.6), I["Scree Color"], b.hsv(I["Scree Color"], val=0.75))
    scree_col = b.mix(b.smooth(b.noise(P, 0.01, detail=4.0), 0.4, 0.7), scree_col, b.hsv(scree_col, val=1.12))
    scree = b.mul(b.smooth(sed, 0.2, 0.65), b.smooth(nz, 0.5, 0.78))
    col = b.mix(scree, rock, scree_col)

    # -- ground cover ------------------------------------------------------
    cos_g = b.math("COSINE", I["Ground Max Slope"])
    g_slope = b.smooth(nz, b.sub(cos_g, 0.05), b.add(cos_g, 0.06))
    jit = b.mul(b.sub(b.noise(P, 0.006, detail=5.0), 0.5), 0.18)
    g_alt = b.inv(b.smooth(b.add(h, jit), b.sub(I["Ground Line"], 0.05), b.add(I["Ground Line"], 0.05)))
    g_raw = b.mul(b.mul(g_slope, g_alt), b.inv(b.mul(b.smooth(flow, 0.75, 1.0), 0.7)))
    breakup = b.sub(b.noise(P, 0.045, detail=6.0, rough=0.65), 0.5)
    ground = b.smooth(b.add(g_raw, breakup), 0.42, 0.58)
    gnoise = b.noise(P, 0.03, detail=5.0)
    gcol = b.mix(b.smooth(gnoise, 0.35, 0.65), I["Ground Color"], I["Ground Color 2"])
    # broad patches of richer and paler grass, as seen across a valley
    gpatch = b.noise(P, 0.004, detail=4.0, rough=0.55)
    gcol = b.mix(b.mul(I["Macro Variation"], 0.9), gcol,
                 b.mix(b.smooth(gpatch, 0.3, 0.7), b.hsv(gcol, sat=1.15, val=0.78), b.hsv(gcol, sat=0.9, val=1.15)))
    dry = b.add(b.mul(b.smooth(b.inv(cav), 0.55, 0.85), 0.5),
                b.mul(b.smooth(h, b.sub(I["Ground Line"], 0.25), I["Ground Line"]), 0.4))
    gcol = b.mix(b.math("MINIMUM", dry, 0.8), gcol, I["Dry Color"])
    # lush in hollows, where water gathers
    gcol = b.mix(b.mul(b.smooth(cav, 0.55, 0.8), 0.4), gcol, b.hsv(gcol, sat=1.2, val=0.85))
    fine = b.noise(P, b.mul(inv_ds, 1.5), detail=3.0)
    gcol = b.mix(b.mul(near, 0.25), gcol, b.mix(fine, b.hsv(gcol, val=0.8), b.hsv(gcol, val=1.15)))
    forest = b.mul(forest_m, b.inv(b.smooth(h, b.sub(I["Forest Line"], 0.06), b.add(I["Forest Line"], 0.02))))
    # from afar a forest is a lumpy canopy: sunlit crowns and dark gaps
    crowns = b.noise(P, 0.09, detail=3.0, rough=0.6)
    canopy = b.mix(b.smooth(crowns, 0.38, 0.66), b.hsv(I["Forest Color"], val=0.7), b.hsv(I["Forest Color"], val=1.4))
    gcol = b.mix(b.math("MINIMUM", b.mul(forest, 1.4), 0.9), gcol, canopy)
    # boulders scattered through the grass, more of them near rock and on steeper ground
    bvor = b.voronoi(P, b.mul(inv_ds, 0.12), feature="F1")
    bmask = b.add(b.mul(b.inv(g_slope), 0.5), b.mul(scree, 0.6))
    bsize = b.mul(b.add(0.1, b.mul(bmask, 0.2)), I["Boulders"])
    boulder = b.mul(b.inv(b.smooth(bvor, b.mul(bsize, 0.7), bsize)), b.inv(forest))
    gcol = b.mix(boulder, gcol, b.mix(b.mul(gravel_v, 0.6), I["Scree Color"], I["Rock Color"]))
    col = b.mix(ground, col, gcol)

    # -- shore -------------------------------------------------------------
    has_water = b.math("GREATER_THAN", I["Water Level"], -0.5)
    wl = b.mul(I["Water Level"], I["Terrain Height"])
    shore_band = b.add(wl, b.add(4.0, b.mul(b.noise(P, 0.02, detail=3.0), 6.0)))
    shore = b.mul(b.mul(b.inv(b.smooth(pz, b.add(wl, 0.5), shore_band)), b.smooth(nz, 0.7, 0.9)), has_water)
    col = b.mix(shore, col, I["Beach Color"])
    under = b.mul(b.inv(b.smooth(pz, b.sub(wl, 1.0), b.add(wl, 0.3))), has_water)
    col = b.mix(b.mul(under, 0.6), col, b.hsv(col, val=0.45))

    # -- snow --------------------------------------------------------------
    sjit = b.add(b.mul(b.sub(b.noise(P, 0.005, detail=6.0), 0.5), 0.2),
                 b.mul(b.sub(b.noise(P, 0.04, detail=4.0), 0.5), 0.06))
    extra = b.mul(b.math("MAXIMUM", b.sub(I["Snow Amount"], 1.0), 0.0), 0.35)
    line = b.sub(I["Snow Line"], extra)
    hs = b.add(h, sjit)
    amount = b.math("MINIMUM", I["Snow Amount"], 1.0)
    s_alt = b.smooth(hs, b.sub(line, 0.035), b.add(line, 0.035))
    cos_s = b.math("COSINE", I["Snow Max Slope"])
    s_slope = b.smooth(nz, b.sub(cos_s, 0.04), b.add(cos_s, 0.1))
    s_loose = b.smooth(nz, b.sub(cos_s, 0.28), cos_s)
    gully = b.add(b.mul(b.smooth(cav, 0.5, 0.8), 0.45), b.mul(flow, 0.25))
    s_raw = b.mul(b.mul(s_alt, b.add(s_slope, b.mul(gully, s_loose))), amount)
    # couloirs hold snow well below the snowline
    s_low = b.smooth(hs, b.sub(line, 0.16), b.sub(line, 0.02))
    couloir = b.mul(b.mul(s_low, b.smooth(b.add(b.mul(cav, 0.8), b.mul(flow, 0.6)), 0.62, 0.85)), s_loose)
    s_raw = b.math("MAXIMUM", s_raw, b.mul(couloir, amount))
    snow = b.smooth(s_raw, 0.42, 0.58)
    # fresh snow on every ledge and bedding plane: the fine normal and the strata draw it in stripes
    d_alt = b.smooth(hs, b.sub(line, 0.2), line)
    ledge = b.smooth(nz_fine, 0.62, 0.8)
    stripe = b.mul(b.smooth(band, 0.56, 0.6), b.mul(steep, 0.6))
    stripe = b.mul(stripe, b.smooth(b.noise(b.vmath("MULTIPLY", P, (1.0, 1.0, 3.0)), 0.03, detail=5.0), 0.5, 0.62))
    dust = b.mul(b.mul(d_alt, b.math("MAXIMUM", ledge, stripe)), b.mul(I["Snow Dusting"], b.inv(ground)))
    dust = b.mul(b.mul(dust, b.smooth(b.noise(P, 0.012, detail=4.0), 0.35, 0.55)), amount)
    snow = b.math("MAXIMUM", snow, b.smooth(dust, 0.25, 0.6))
    snow_tint = b.mix(b.mul(b.smooth(cav, 0.5, 0.9), 0.5), I["Snow Color"],
                      b.mix(0.5, I["Snow Color"], "#a9bcd6", blend="MULTIPLY"))
    col = b.mix(snow, col, snow_tint)

    # baked occlusion: gullies, couloirs and the feet of walls get less sky (snow keeps more light)
    occ = b.mixf(b.mul(I["Occlusion Strength"], b.sub(1.0, b.mul(snow, 0.5))), 1.0,
                 b.math("POWER", ao, 1.5))
    col = b.mix(1.0, col, b.combine(occ, occ, occ), blend="MULTIPLY")
    # and a little cavity shading where the baked occlusion is too coarse to see
    cocc = b.remap(cav, 0.3, 0.85, 1.06, 0.8)
    col = b.mix(b.mul(keep, 0.7), col, b.mix(1.0, col, b.combine(cocc, cocc, cocc), blend="MULTIPLY"))

    # -- surface -----------------------------------------------------------
    rough = b.mixf(ground, 0.84, 0.93)
    rough = b.mixf(scree, rough, 0.9)
    rough = b.mixf(snow, rough, 0.42)
    rough = b.mixf(under, rough, 0.25)

    rock_h = b.add(b.mul(b.noise(P, inv_ds, detail=8.0, rough=0.62), 0.7),
                   b.mul(b.inv(crack), b.mul(I["Cracks"], 0.35)))
    rock_h = b.add(rock_h, b.mul(b.mul(band, I["Strata"]), b.mul(mid, 0.6)))
    rock_h = b.add(rock_h, b.mul(b.mul(flute, steep), 0.3))
    ground_h = b.mul(b.noise(P, b.mul(inv_ds, 3.0), detail=4.0), 0.25)
    ground_h = b.add(ground_h, b.mul(boulder, 0.6))
    rip_dir = b.add(b.mul(px, 0.82), b.mul(py, 0.57))
    rip_warp = b.mul(b.noise(P, 0.15, detail=3.0), 7.0)
    ripple = b.math("SINE", b.add(b.mul(rip_dir, 2.0 * math.pi / 0.32), rip_warp))
    ripple2 = b.mul(b.math("SINE", b.add(b.mul(rip_dir, 2.0 * math.pi / 3.5), b.mul(rip_warp, 0.4))), 0.6)
    ground_h = b.add(ground_h, b.mul(b.add(ripple, ripple2), b.mul(I["Ripples"], 0.25)))
    snow_h = b.mul(b.noise(P, b.mul(inv_ds, 0.3), detail=3.0), 0.2)
    height = b.mixf(ground, rock_h, ground_h)
    height = b.mixf(scree, height, b.mul(gravel_v, 0.5))
    height = b.mixf(snow, height, snow_h)
    # the surroundings have no baked normal map: give their slopes some broad relief instead
    knolls = b.noise(P, 0.012, detail=6.0, rough=0.6)
    N_ap = b.bump(knolls, strength=b.mul(apron, 0.35), distance=6.0, normal=N)
    # big walls at any distance: buttresses and vertical fluting, tens of metres across
    buttress = b.noise(b.vmath("MULTIPLY", P, (1.0, 1.0, 0.25)), 0.012, detail=5.0, rough=0.6)
    fluting = b.noise(b.vmath("MULTIPLY", P, (1.0, 1.0, 0.08)), 0.05, detail=4.0, rough=0.55)
    relief = b.add(buttress, b.mul(fluting, 0.5))
    N_ap = b.bump(relief, strength=b.mul(b.mul(steep, keep), 0.6), distance=30.0, normal=N_ap)
    bump_n = b.bump(height, strength=b.mul(I["Detail Strength"], b.add(near, b.mul(mid, 0.25))),
                    distance=b.mul(ds, 0.12), normal=N_ap)

    bsdf = b.node("ShaderNodeBsdfPrincipled", {"Base Color": col, "Roughness": rough, "Normal": bump_n})
    b.links.new(haze.mix(b, b.out(bsdf), I["Haze"]), find(go.inputs, "Surface"))
    rock_mask = b.mul(b.inv(ground), b.inv(snow))
    b.links.new(snow, find(go.inputs, "Snow"))
    b.links.new(b.mul(rock_mask, b.inv(scree)), find(go.inputs, "Rock"))
    b.links.new(ground, find(go.inputs, "Ground"))
    nodekit.arrange(tree)
    tree["sm_version"] = GROUP_VERSION


def surface_group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None and g.bl_idname == "ShaderNodeTree" and g.get("sm_version", 1) < GROUP_VERSION:
        # a file from an older Summit: its materials keep the old group, new ones get the current one
        g.name = f"{GROUP} v{g.get('sm_version', 1)}"
        g = None
    if g is None or g.bl_idname != "ShaderNodeTree":
        g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
        _build(g)
    return g


def _value(name, v):
    if name in ANGLE_INPUTS:
        return math.radians(v)
    if isinstance(v, str):
        return nodekit.hex_color(v)
    return v


def apply_values(group_node, values):
    for k, v in values.items():
        if k in group_node.inputs:
            group_node.inputs[k].default_value = _value(k, v)


def surface_node(mat):
    """The SM Terrain Surface group node of a terrain material, or None."""
    if mat is None or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == "GROUP" and n.node_tree and n.node_tree.name.startswith(GROUP):
            return n
    return None


def terrain_material(name, normal_img, mask_img, height, biome_id, extra=None):
    """A material that feeds a terrain's baked maps into the shared surface group."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    b = NB(tree)
    uv = b.out(b.node("ShaderNodeTexCoord"), "UV")
    nimg = b.node("ShaderNodeTexImage", {"Vector": uv}, image=normal_img, interpolation="Cubic",
                  extension="EXTEND", label="Normal Map")
    mimg = b.node("ShaderNodeTexImage", {"Vector": uv}, image=mask_img, interpolation="Linear",
                  extension="EXTEND", label="Masks: flow, sediment, cavity, forest")
    nmap = b.node("ShaderNodeNormalMap", {"Color": b.out(nimg, "Color")}, space="OBJECT")
    sep = b.node("ShaderNodeSeparateColor", {"Color": b.out(mimg, "Color")})
    grp = b.node("ShaderNodeGroup", node_tree=surface_group())
    grp.name = grp.label = "Summit Surface"
    b.links.new(b.out(nmap), grp.inputs["Normal"])
    b.links.new(sep.outputs[0], grp.inputs["Flow"])
    b.links.new(sep.outputs[1], grp.inputs["Sediment"])
    b.links.new(sep.outputs[2], grp.inputs["Cavity"])
    b.links.new(b.out(mimg, "Alpha"), grp.inputs["Forest"])
    b.links.new(b.out(nimg, "Alpha"), grp.inputs["Occlusion"])
    grp.inputs["Terrain Height"].default_value = height
    apply_values(grp, biomes.surface_values(biome_id))
    apply_values(grp, extra or {})
    out = b.node("ShaderNodeOutputMaterial")
    b.links.new(grp.outputs["Surface"], out.inputs["Surface"])
    nodekit.arrange(tree, dx=300, dy=320)
    grp.width = 220
    return mat


def water_material(name, deep, shallow):
    """Clear dark water with small waves; reads well from a distance and stays cheap."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    b = NB(tree)
    P = b.out(b.node("ShaderNodeTexCoord"), "Object")
    waves = b.add(b.noise(b.vmath("MULTIPLY", P, (1.0, 2.2, 1.0)), 0.35, detail=4.0, rough=0.55),
                  b.mul(b.noise(P, 2.5, detail=3.0), 0.3))
    dist = b.out(b.node("ShaderNodeCameraData"), "View Distance")
    calm = b.inv(b.smooth(dist, 50.0, 3000.0))
    nrm = b.bump(waves, strength=b.add(0.05, b.mul(calm, 0.25)), distance=0.15)
    fres = b.out(b.node("ShaderNodeLayerWeight", {"Blend": 0.35}), "Facing")
    col = b.mix(b.smooth(fres, 0.2, 0.9), shallow, deep)
    bsdf = b.node("ShaderNodeBsdfPrincipled", {"Base Color": col, "Roughness": 0.04, "IOR": 1.333,
                                               "Normal": nrm, "Specular IOR Level": 0.6})
    out = b.node("ShaderNodeOutputMaterial")
    b.links.new(haze.mix(b, b.out(bsdf)), out.inputs["Surface"])
    nodekit.arrange(tree)
    return mat
