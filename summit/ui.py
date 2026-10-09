# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar panels: Library, Horizon, and the active terrain's Shape, Look, Forests and Water."""

import bpy

from . import biomes, forest, haze, presets, surface, terrain

# look controls shown on the Terrain panel, by section; the rest stay in the material
LOOK = [
    ("Snow", ("Snow Line", "Snow Amount", "Snow Max Slope", "Snow Dusting")),
    ("Vegetation", ("Ground Line", "Ground Max Slope", "Forest Line", "Boulders")),
    ("Rock", ("Strata", "Strata Scale", "Cracks", "Occlusion Strength")),
    ("Colours", ("Rock Color", "Rock Color 2", "Ground Color", "Ground Color 2", "Snow Color")),
    ("Distance", ("Haze", "Detail Distance", "Detail Strength")),
]
LAYER_MAIN = ("Density", "Tree Line", "Tree Height", "Viewport Amount")
LAYER_MORE = ("Lowest", "Max Slope", "Min Distance", "Clumping", "Height Random", "Shrink at Tree Line", "Seed")


class SM_PT_base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Summit"


class SM_PT_library(SM_PT_base, bpy.types.Panel):
    bl_label = "Library"
    bl_idname = "SM_PT_library"

    def draw(self, context):
        sp = context.scene.summit
        col = self.layout.column()
        col.row(align=True).prop(sp, "category", expand=True, icon_only=True)
        col.template_icon_view(sp, "preset", show_labels=True, scale=7.0, scale_popup=5.0)
        p = presets.PRESET_BY_ID.get(sp.preset)
        if p:
            box = col.box()
            box.label(text=p.label, icon=presets.CATEGORY_ICON[p.category])
            for line in _wrap(p.description, 38):
                box.label(text=line)
        col.prop(sp, "biome")
        sub = col.column(align=True)
        sub.prop(sp, "size")
        sub.prop(sp, "height")
        sub = col.column(align=True)
        sub.prop(sp, "seed")
        sub.prop(sp, "erosion", slider=False)
        col.prop(sp, "quality")
        row = col.row(align=True)
        row.prop(sp, "forests", toggle=True, icon="OUTLINER_OB_FORCE_FIELD")
        row.prop(sp, "water", toggle=True, icon="MOD_OCEAN")
        row = col.row(align=True)
        row.prop(sp, "surroundings", toggle=True, icon="MESH_CIRCLE")
        row.prop(sp, "distant", toggle=True, icon="WORLD")
        col.prop(sp, "frame")
        row = col.row()
        row.scale_y = 1.5
        row.operator("sm.add_terrain", icon="ADD")


class SM_PT_horizon(SM_PT_base, bpy.types.Panel):
    bl_label = "Horizon"
    bl_idname = "SM_PT_horizon"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        sp = context.scene.summit
        col = self.layout.column()
        col.label(text="A ring of distant mountains around the scene")
        col.template_icon_view(sp, "horizon_style", show_labels=True, scale=5.0, scale_popup=5.0)
        col.prop(sp, "horizon_biome")
        sub = col.column(align=True)
        sub.prop(sp, "horizon_radius")
        sub.prop(sp, "horizon_depth")
        sub.prop(sp, "horizon_height")
        col.prop(sp, "horizon_seed")
        col.prop(sp, "horizon_quality")
        row = col.row()
        row.scale_y = 1.3
        row.operator("sm.add_horizon", icon="WORLD")


class SM_PT_terrain(SM_PT_base, bpy.types.Panel):
    bl_label = "Terrain"
    bl_idname = "SM_PT_terrain"

    def draw(self, context):
        obj = context.active_object
        layout = self.layout
        if not terrain.is_terrain(obj):
            layout.label(text="Select a Summit terrain", icon="INFO")
            return
        s = terrain.settings(obj)
        col = layout.column()
        name = presets.PRESET_BY_ID[s["preset"]].label if s["preset"] in presets.PRESET_BY_ID \
            else presets.HORIZON_BY_ID.get(s["preset"], ("", s["preset"]))[1]
        col.label(text=f"{name}  ·  seed {s['seed']}  ·  {s['quality'].title()}", icon="RNDCURVE")
        row = col.row(align=True)
        row.operator("sm.regenerate", icon="FILE_REFRESH")
        row.operator("sm.reseed", text="", icon="MOD_NOISE")
        b = biomes.BIOME_BY_ID.get(s["biome"])
        col.operator_menu_enum("sm.set_biome", "biome", text=f"Biome: {b.label if b else s['biome']}",
                               icon="WORLD_DATA")
        if s["kind"] == "TERRAIN":
            col.operator("sm.frame_shot", icon="VIEW_CAMERA")


class SM_PT_haze(SM_PT_base, bpy.types.Panel):
    bl_label = "Haze"
    bl_idname = "SM_PT_haze"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        sc = context.scene
        col = self.layout.column()
        if haze.DENSITY not in sc:
            col.label(text="Aerial perspective for all Summit terrains")
            col.operator("sm.add_haze", icon="ADD")
            return
        col.prop(sc, f'["{haze.DENSITY}"]', text="Density")
        col.prop(sc, f'["{haze.HEIGHT}"]', text="Thins Out Over")
        col.prop(sc, f'["{haze.COLOR}"]', text="Colour")


class SM_PT_look(SM_PT_base, bpy.types.Panel):
    bl_label = "Look"
    bl_idname = "SM_PT_look"
    bl_parent_id = "SM_PT_terrain"

    @classmethod
    def poll(cls, context):
        return terrain.is_terrain(context.active_object) and surface.surface_node(context.active_object.active_material)

    def draw(self, context):
        node = surface.surface_node(context.active_object.active_material)
        layout = self.layout
        for title, keys in LOOK:
            col = layout.column(align=True)
            col.label(text=title)
            for k in keys:
                sock = node.inputs[k]
                if sock.is_linked:
                    continue
                col.prop(sock, "default_value", text=k)
        layout.label(text="Everything else is on the Summit Surface node", icon="NODE_MATERIAL")


class SM_PT_forests(SM_PT_base, bpy.types.Panel):
    bl_label = "Forests"
    bl_idname = "SM_PT_forests"
    bl_parent_id = "SM_PT_terrain"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return terrain.is_terrain(obj) and terrain.settings(obj)["kind"] == "TERRAIN"

    def draw(self, context):
        obj = context.active_object
        layout = self.layout
        layout.operator_menu_enum("sm.add_forest", "species", icon="ADD")
        for mod in forest.layers(obj):
            box = layout.box()
            head = box.row(align=True)
            head.prop(mod, "show_expanded", text="", emboss=False,
                      icon="DOWNARROW_HLT" if mod.show_expanded else "RIGHTARROW")
            head.prop(mod, "name", text="")
            head.prop(mod, "show_viewport", text="")
            head.prop(mod, "show_render", text="")
            op = head.operator("sm.reseed_layer", text="", icon="FILE_REFRESH")
            op.modifier = mod.name
            op = head.operator("sm.remove_layer", text="", icon="X")
            op.modifier = mod.name
            if not mod.show_expanded:
                continue
            col = box.column(align=True)
            for key in LAYER_MAIN:
                forest.draw_input(col, mod, key)
            sub = box.column(align=True)
            for key in LAYER_MORE:
                forest.draw_input(sub, mod, key)


class SM_PT_water(SM_PT_base, bpy.types.Panel):
    bl_label = "Water"
    bl_idname = "SM_PT_water"
    bl_parent_id = "SM_PT_terrain"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return terrain.is_terrain(obj) and terrain.settings(obj)["kind"] == "TERRAIN"

    def draw(self, context):
        obj = context.active_object
        water = terrain.water_object(obj)
        col = self.layout.column()
        if water is None:
            op = col.operator("sm.water", text="Add Water", icon="MOD_OCEAN")
            op.level = 0.1
            return
        col.prop(water, "location", index=2, text="Water Height")
        op = col.operator("sm.water", text="Remove Water", icon="X")
        op.level = -1.0


def _wrap(text, width):
    lines, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


classes = (SM_PT_library, SM_PT_horizon, SM_PT_haze, SM_PT_terrain, SM_PT_look, SM_PT_forests, SM_PT_water)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
