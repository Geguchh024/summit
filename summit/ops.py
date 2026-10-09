# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators: add terrains and horizons, regenerate, re-dress, manage forests and water."""

import random
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import biomes, forest, haze, presets, terrain, trees
from .props import QUALITY_ITEMS


def _select_only(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def fit_view(context, extent):
    """Make sure viewports and the camera can see a terrain this big."""
    need = extent * 3.0
    changed = False
    for area in context.screen.areas if context.screen else ():
        if area.type == "VIEW_3D":
            space = area.spaces.active
            if space.clip_end < need:
                space.clip_end = need
                space.clip_start = max(space.clip_start, need / 200000.0)
                changed = True
    cam = context.scene.camera
    if cam and cam.type == "CAMERA" and cam.data.clip_end < need:
        cam.data.clip_end = need
        changed = True
    return changed


def ensure_transparency(context):
    """Forests are stacks of transparent cards: give Cycles enough transparent bounces."""
    cyc = getattr(context.scene, "cycles", None)
    if cyc is not None and cyc.transparent_max_bounces < 128:
        cyc.transparent_max_bounces = 128
        return True
    return False


def _active_terrain(context):
    obj = context.active_object
    return obj if terrain.is_terrain(obj) else None


class SM_OT_add_terrain(bpy.types.Operator):
    """Generate the chosen landform at the 3D cursor"""
    bl_idname = "sm.add_terrain"
    bl_label = "Add Terrain"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sp = context.scene.summit
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        p = presets.PRESET_BY_ID[sp.preset]
        s = terrain.terrain_settings(p.id, sp.seed, sp.quality, sp.size, sp.height, sp.erosion,
                                     None if sp.biome == "AUTO" else sp.biome, sp.forests, sp.water,
                                     sp.surroundings)
        t = time.time()
        obj = terrain.create(context, s, p.label, context.scene.cursor.location.copy())
        extent = s["size"] * (2.0 * terrain.APRON_REACH if s["apron"] else 1.0)
        if sp.distant:
            terrain.add_distant_mountains(context, obj)
            extent += s["size"] * 4.0
        _select_only(context, obj)
        fit_view(context, extent)
        if sp.frame:
            context.view_layer.update()
            terrain.frame_shot(context, obj)
        if s["forests"] and biomes.BIOME_BY_ID[s["biome"]].forests:
            ensure_transparency(context)
        self.report({"INFO"}, f"{p.label} generated in {time.time() - t:.1f} s")
        return {"FINISHED"}


class SM_OT_add_horizon(bpy.types.Operator):
    """Surround the scene with a ring of distant mountains, centred on the 3D cursor"""
    bl_idname = "sm.add_horizon"
    bl_label = "Add Horizon"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sp = context.scene.summit
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        s = terrain.horizon_settings(sp.horizon_style, sp.horizon_seed, sp.horizon_quality, sp.horizon_radius,
                                     sp.horizon_depth, sp.horizon_height,
                                     None if sp.horizon_biome == "AUTO" else sp.horizon_biome)
        label = presets.HORIZON_BY_ID[sp.horizon_style][1]
        t = time.time()
        obj = terrain.create(context, s, f"Horizon {label}", context.scene.cursor.location.copy())
        _select_only(context, obj)
        fit_view(context, s["size"])
        self.report({"INFO"}, f"Horizon generated in {time.time() - t:.1f} s")
        return {"FINISHED"}


class SM_OT_frame_shot(bpy.types.Operator):
    """Aim the scene camera at the summit from inside the landscape, side-lit by the sun.
Each click tries another angle"""
    bl_idname = "sm.frame_shot"
    bl_label = "Frame Shot"
    bl_options = {"REGISTER", "UNDO"}

    view: IntProperty(name="Angle", min=0, description="Which viewpoint around the summit")
    elevation: FloatProperty(name="Camera Height", default=0.1, min=0.0, soft_max=1.0,
                             description="Height above the ground, as a fraction of the terrain height")
    lens: FloatProperty(name="Focal Length", default=35.0, min=8.0, soft_max=200.0, unit="CAMERA")

    @classmethod
    def poll(cls, context):
        obj = _active_terrain(context)
        return obj is not None and terrain.settings(obj)["kind"] == "TERRAIN"

    def invoke(self, context, event):
        obj = _active_terrain(context)
        self.view = obj.get("sm_view", -1) + 1
        return self.execute(context)

    def execute(self, context):
        obj = _active_terrain(context)
        obj["sm_view"] = self.view
        cam = terrain.frame_shot(context, obj, self.view, self.elevation, self.lens)
        fit_view(context, terrain.settings(obj)["size"] * 6.0)
        for area in context.screen.areas if context.screen else ():
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
        self.report({"INFO"}, f"Camera: {cam.name}")
        return {"FINISHED"}


class SM_OT_add_haze(bpy.types.Operator):
    """Give the scene aerial haze: distant terrains, forests and water fade into the colour of the air"""
    bl_idname = "sm.add_haze"
    bl_label = "Add Haze"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        haze.ensure(context.scene)
        context.scene.update_tag()
        return {"FINISHED"}


class SM_OT_regenerate(bpy.types.Operator):
    """Rebuild the terrain's shape. Its material, look settings and forests are kept"""
    bl_idname = "sm.regenerate"
    bl_label = "Regenerate"
    bl_options = {"REGISTER", "UNDO"}

    seed: IntProperty(name="Seed", min=0)
    quality: EnumProperty(name="Quality", items=QUALITY_ITEMS)
    size: FloatProperty(name="Size", min=10.0, unit="LENGTH")
    height: FloatProperty(name="Height", min=1.0, unit="LENGTH")
    erosion: FloatProperty(name="Erosion", min=0.0, soft_max=3.0)

    @classmethod
    def poll(cls, context):
        return _active_terrain(context) is not None

    def invoke(self, context, event):
        s = terrain.settings(_active_terrain(context))
        self.seed, self.quality, self.height, self.erosion = s["seed"], s["quality"], s["height"], s["erosion"]
        self.size = s["size"]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        s = terrain.settings(_active_terrain(context))
        col = self.layout.column()
        col.prop(self, "seed")
        col.prop(self, "quality")
        if s["kind"] == "TERRAIN":
            col.prop(self, "size")
        col.prop(self, "height")
        col.prop(self, "erosion")

    def execute(self, context):
        obj = _active_terrain(context)
        changes = dict(seed=self.seed, quality=self.quality, height=self.height, erosion=self.erosion)
        if terrain.settings(obj)["kind"] == "TERRAIN":
            changes["size"] = self.size
        t = time.time()
        terrain.regenerate(context, obj, **changes)
        fit_view(context, terrain.settings(obj)["size"])
        self.report({"INFO"}, f"Regenerated in {time.time() - t:.1f} s")
        return {"FINISHED"}


class SM_OT_reseed(bpy.types.Operator):
    """Regenerate the terrain with a new random seed"""
    bl_idname = "sm.reseed"
    bl_label = "New Seed"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_terrain(context) is not None

    def execute(self, context):
        terrain.regenerate(context, _active_terrain(context), seed=random.randint(0, 99999))
        return {"FINISHED"}


class SM_OT_set_biome(bpy.types.Operator):
    """Re-dress the terrain with another biome"""
    bl_idname = "sm.set_biome"
    bl_label = "Set Biome"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "biome"

    biome: EnumProperty(name="Biome", items=[(b.id, b.label, b.description) for b in biomes.BIOMES])
    forests: BoolProperty(name="Replace Forests", default=True,
                          description="Swap the forest layers for the new biome's trees")

    @classmethod
    def poll(cls, context):
        return _active_terrain(context) is not None

    def execute(self, context):
        obj = _active_terrain(context)
        terrain.set_biome(obj, self.biome, self.forests)
        if self.forests and biomes.BIOME_BY_ID[self.biome].forests:
            ensure_transparency(context)
        return {"FINISHED"}


class SM_OT_water(bpy.types.Operator):
    """Add or remove water on the terrain"""
    bl_idname = "sm.water"
    bl_label = "Water"
    bl_options = {"REGISTER", "UNDO"}

    level: FloatProperty(name="Level", default=0.1, min=-1.0, max=1.0,
                         description="Water level as a fraction of the terrain height; -1 removes the water")

    @classmethod
    def poll(cls, context):
        obj = _active_terrain(context)
        return obj is not None and terrain.settings(obj)["kind"] == "TERRAIN"

    def execute(self, context):
        terrain.set_water(_active_terrain(context), self.level)
        return {"FINISHED"}


class SM_OT_add_forest(bpy.types.Operator):
    """Add a forest layer of the chosen trees to the terrain"""
    bl_idname = "sm.add_forest"
    bl_label = "Add Forest"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "species"

    species: EnumProperty(name="Trees", items=[(k, v["label"], f"Impostor {v['label'].lower()} trees")
                                               for k, v in trees.SPECIES.items()])

    @classmethod
    def poll(cls, context):
        return _active_terrain(context) is not None

    def execute(self, context):
        obj = _active_terrain(context)
        s = terrain.settings(obj)
        f = biomes.Forest(self.species, 150.0, 0.5, height=4.0 if self.species == "SHRUB" else 16.0)
        coll = trees.species_collection(self.species)
        forest.add_layer(obj, coll, f"SM {trees.SPECIES[self.species]['label']} Forest",
                         **terrain.forest_values(f, s))
        ensure_transparency(context)
        return {"FINISHED"}


class SM_OT_remove_layer(bpy.types.Operator):
    """Remove this forest layer"""
    bl_idname = "sm.remove_layer"
    bl_label = "Remove Layer"
    bl_options = {"REGISTER", "UNDO"}

    modifier: StringProperty()

    def execute(self, context):
        obj = context.active_object
        mod = obj.modifiers.get(self.modifier) if obj else None
        if mod is None:
            return {"CANCELLED"}
        obj.modifiers.remove(mod)
        return {"FINISHED"}


class SM_OT_reseed_layer(bpy.types.Operator):
    """Pick a new random layout for this forest layer"""
    bl_idname = "sm.reseed_layer"
    bl_label = "New Seed"
    bl_options = {"REGISTER", "UNDO"}

    modifier: StringProperty()

    def execute(self, context):
        obj = context.active_object
        mod = obj.modifiers.get(self.modifier) if obj else None
        if mod is None:
            return {"CANCELLED"}
        forest.set_value(mod, "Seed", random.randint(0, 99999))
        return {"FINISHED"}


classes = (SM_OT_add_terrain, SM_OT_add_horizon, SM_OT_frame_shot, SM_OT_add_haze, SM_OT_regenerate, SM_OT_reseed, SM_OT_set_biome, SM_OT_water,
           SM_OT_add_forest, SM_OT_remove_layer, SM_OT_reseed_layer)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
