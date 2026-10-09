# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless test suite.

    blender -b --factory-startup --python tests/run_tests.py

Exits with a non-zero status when any test fails.
"""

import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bpy  # noqa: E402
import numpy as np  # noqa: E402

import summit  # noqa: E402

summit.register()
from summit import biomes, field, forest, generate, haze, presets, recipes, surface, terrain, trees  # noqa: E402

TMP = tempfile.mkdtemp(prefix="sm_tests_")
results = []


def test(fn):
    results.append(fn)
    return fn


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make(preset="ALPINE_PEAK", **kw):
    s = terrain.terrain_settings(preset, kw.pop("seed", 0), kw.pop("quality", "PREVIEW"), **kw)
    return terrain.create(bpy.context, s, preset)


def instances_of(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    return [i.object.original for i in dg.object_instances
            if i.is_instance and i.parent and i.parent.original == obj]


# -- engine (no bpy) --------------------------------------------------------

@test
def every_landform_generates():
    for sid in recipes.SHAPES:
        ring = (3000.0, 2500.0) if sid.startswith("H_") else None
        m = generate.generate(sid, 1, "PREVIEW", 2000.0, 500.0, ring=ring)
        assert np.isfinite(m.h).all(), sid
        assert abs(float(m.h.min())) < 0.05 and m.h.max() > 0.9, (sid, m.h.min(), m.h.max())
        for k in ("flow", "sediment", "cavity", "forest", "ao"):
            a = getattr(m, k)
            assert a.shape == m.h.shape and 0.0 <= a.min() and a.max() <= 1.0, (sid, k)


@test
def generation_is_deterministic():
    a = generate.generate("CANYON", 5, "PREVIEW", 2000.0, 400.0)
    b = generate.generate("CANYON", 5, "PREVIEW", 2000.0, 400.0)
    c = generate.generate("CANYON", 6, "PREVIEW", 2000.0, 400.0)
    assert np.array_equal(a.h, b.h)
    assert not np.array_equal(a.h, c.h)


@test
def erosion_is_stable():
    # many droplets in one cell used to dig runaway pits
    c = recipes.Ctx(128, 128, 3)
    h = field.normalize(recipes.alpine_peak(c)) * 60.0
    out, flow, dep = field.erode_hydraulic(h, 128 * 128 * 3, np.random.default_rng(0))
    assert np.isfinite(out).all()
    assert out.min() > -2.0 and out.max() <= h.max() + 1.0, (out.min(), out.max())
    assert flow.max() > 0 and dep.max() > 0


@test
def horizon_tiles_seamlessly():
    m = generate.generate("H_PEAKS", 2, "PREVIEW", ring=(3000.0, 2500.0))
    seam = np.abs(m.h[:, 0] - m.h[:, -1]).mean()
    step = np.abs(np.diff(m.h, axis=1)).mean()
    assert seam < step * 3.0, (seam, step)


# -- Blender ----------------------------------------------------------------

@test
def terrain_object_is_complete():
    reset()
    obj = make()
    me = obj.data
    res = generate.QUALITY["PREVIEW"][2]
    assert len(me.vertices) == res ** 2 + generate.apron_loops(res) * 4 * (res - 1)
    for key in ("sm_forest", "sm_flow", "sm_sediment", "sm_apron"):
        assert key in me.attributes, key
    apron = np.empty(len(me.vertices))
    me.attributes["sm_apron"].data.foreach_get("value", apron)
    assert apron[: res * res].max() == 0.0 and apron[-1] == 1.0
    node = surface.surface_node(obj.active_material)
    assert node is not None
    imgs = [n.image for n in obj.active_material.node_tree.nodes if n.type == "TEX_IMAGE"]
    assert len(imgs) == 2 and all(i.packed_file for i in imgs)
    z = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", z)
    assert abs(z[2::3].max() - 1600.0) < 60.0, z[2::3].max()
    assert len(forest.layers(obj)) == len(biomes.BIOME_BY_ID["ALPINE"].forests)


@test
def terrain_without_surroundings():
    reset()
    obj = make(surroundings=False)
    res = generate.QUALITY["PREVIEW"][2]
    assert len(obj.data.vertices) == res ** 2
    assert "sm_apron" not in obj.data.attributes


@test
def surroundings_join_the_terrain():
    # the first loop of the surroundings starts at the terrain's own border height
    res = 64
    edge = generate.perimeter(res)
    u = np.linspace(0.0, 1.0, res)
    U, V = np.meshgrid(u, u)
    xy = np.stack([(U - 0.5) * 4000.0, (V - 0.5) * 4000.0], -1).reshape(-1, 2)[edge]
    z = 300.0 + 200.0 * np.sin(np.arange(len(edge)) * 0.1)
    co, forest_mask, blend = generate.apron(xy, z, 4000.0, 1600.0, loops=generate.apron_loops(res))
    assert np.abs(co[0, :, 2] - z).max() < 60.0
    r = np.hypot(co[-1, :, 0], co[-1, :, 1])
    assert np.allclose(r, 1.5 * 4000.0, rtol=1e-3), (r.min(), r.max())
    assert 0.0 <= forest_mask.min() and forest_mask.max() <= 1.0 and blend[-1].min() == 1.0


@test
def frame_shot_sees_the_terrain():
    reset()
    obj = make()
    bpy.context.view_layer.update()
    cam = terrain.frame_shot(bpy.context, obj)
    assert bpy.context.scene.camera is cam
    # the camera is inside the landscape, above the ground, and the terrain is in view
    loc = cam.location
    assert np.hypot(loc.x, loc.y) < terrain.APRON_REACH * 4000.0
    hit, *_ = obj.ray_cast(loc, (0.0, 0.0, -1.0))
    assert hit
    fwd = cam.matrix_world.to_3x3() @ __import__("mathutils").Vector((0.0, 0.0, -1.0))
    hit, *_ = obj.ray_cast(loc, (fwd.x, fwd.y, fwd.z - 0.2))
    assert hit


@test
def haze_is_shared_by_the_scene():
    reset()
    assert haze.DENSITY not in bpy.context.scene
    make()
    sc = bpy.context.scene
    assert sc[haze.DENSITY] == presets.PRESET_BY_ID["ALPINE_PEAK"].haze
    # trees read it too
    mat = trees.species_collection("FIR").objects[0].active_material
    names = {n.attribute_name for n in mat.node_tree.nodes if n.type == "ATTRIBUTE"}
    assert haze.DENSITY in names


@test
def older_shader_group_is_kept_aside():
    # a file saved by an older Summit holds an older SM Terrain Surface: new terrains must still build
    reset()
    old = make()
    group = surface.surface_node(old.active_material).node_tree
    group["sm_version"] = 1
    new = make("DUNES")
    assert group.name == f"{surface.GROUP} v1"
    assert surface.surface_node(old.active_material).node_tree is group
    assert surface.surface_node(new.active_material).node_tree.get("sm_version") == surface.GROUP_VERSION


@test
def every_preset_builds_in_blender():
    for p in presets.PRESETS:
        reset()
        obj = make(p.id)
        assert obj.active_material is not None, p.id
        water = terrain.water_object(obj)
        assert (water is not None) == (p.water > -0.5), p.id


@test
def forests_grow_trees():
    reset()
    obj = make("ROLLING_HILLS")
    insts = instances_of(obj)
    assert len(insts) > 50, len(insts)
    assert all(o.get("sm_species") for o in insts[:50])


@test
def tree_cards_exist():
    for info in trees.SPECIES.values():
        for card in info["cards"]:
            assert os.path.exists(os.path.join(trees.CARD_DIR, card + ".png")), card
            assert os.path.exists(os.path.join(trees.CARD_DIR, card + "_N.png")), card
            trees.card_info(card)
    reset()
    coll = trees.species_collection("FIR")
    assert len(coll.objects) == len(trees.SPECIES["FIR"]["cards"])
    assert all(o.data.materials[0].node_tree for o in coll.objects)


@test
def regenerate_keeps_material_and_forests():
    reset()
    obj = make()
    mat = obj.active_material
    node = surface.surface_node(mat)
    node.inputs["Snow Line"].default_value = 0.3
    n_layers = len(forest.layers(obj))
    terrain.regenerate(bpy.context, obj, seed=9, height=900.0)
    assert obj.active_material is mat
    assert abs(surface.surface_node(mat).inputs["Snow Line"].default_value - 0.3) < 1e-6
    assert surface.surface_node(mat).inputs["Terrain Height"].default_value == 900.0
    assert len(forest.layers(obj)) == n_layers
    assert terrain.settings(obj)["seed"] == 9


@test
def biome_switch():
    reset()
    obj = make()
    terrain.set_biome(obj, "CANYON")
    node = surface.surface_node(obj.active_material)
    assert abs(node.inputs["Strata"].default_value - biomes.surface_values("CANYON")["Strata"]) < 1e-6
    assert all("Shrub" in m.name for m in forest.layers(obj))


@test
def water_follows_plane():
    reset()
    obj = make("ROLLING_HILLS")
    terrain.set_water(obj, 0.2)
    water = terrain.water_object(obj)
    assert water is not None and abs(water.location.z - 0.2 * 160.0) < 1e-3
    for mod in forest.layers(obj):
        assert forest.get(mod, "Lowest") >= 0.2
    terrain.set_water(obj, -1.0)
    assert terrain.water_object(obj) is None


@test
def horizon_object():
    reset()
    s = terrain.horizon_settings("H_HILLS", 0, "PREVIEW", radius=2000.0, depth=1500.0)
    obj = terrain.create(bpy.context, s, "Horizon")
    co = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", co)
    r = np.hypot(co[0::3], co[1::3])
    assert 1990.0 < r.min() and r.max() < 3510.0, (r.min(), r.max())
    assert not forest.layers(obj)


@test
def survives_save_and_reload_without_addon():
    reset()
    make("CANYON")
    path = os.path.join(TMP, "t.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    summit.unregister()
    try:
        bpy.ops.wm.open_mainfile(filepath=path)
        obj = bpy.data.objects["CANYON"]
        assert all(img.packed_file for img in bpy.data.images if img.users)
        assert len(instances_of(obj)) > 0
    finally:
        summit.register()


@test
def operators_run():
    reset()
    sp = bpy.context.scene.summit
    sp.category = "DESERT"
    sp.preset = "DUNES"
    sp.quality = "PREVIEW"
    assert bpy.ops.sm.add_terrain() == {"FINISHED"}
    obj = bpy.context.active_object
    assert terrain.is_terrain(obj)
    assert bpy.ops.sm.reseed() == {"FINISHED"}
    assert bpy.ops.sm.add_forest(species="SHRUB") == {"FINISHED"}
    sp.horizon_quality = "PREVIEW"
    assert bpy.ops.sm.add_horizon() == {"FINISHED"}
    bpy.context.view_layer.objects.active = obj
    assert bpy.ops.sm.frame_shot("EXEC_DEFAULT", view=1) == {"FINISHED"}
    assert terrain.horizon_object(obj) is not None   # Distant Mountains is on by default


# ---------------------------------------------------------------------------

failed = 0
for fn in results:
    try:
        fn()
        print(f"PASS {fn.__name__}")
    except Exception:  # noqa: BLE001 - report every failure, keep going
        failed += 1
        print(f"FAIL {fn.__name__}")
        traceback.print_exc()
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
