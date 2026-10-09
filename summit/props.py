# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene settings: the library browser and the horizon options."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty

from . import biomes, presets, thumbs

# Blender needs the enum item lists to stay alive while it shows them
_items_cache = {}

QUALITY_ITEMS = [
    ("PREVIEW", "Preview", "Fast draft: 512 px maps, 128 x 128 mesh", 0),
    ("MEDIUM", "Medium", "1K maps, 256 x 256 mesh. Good for backgrounds", 1),
    ("HIGH", "High", "2K maps, 512 x 512 mesh. Good for most shots", 2),
    ("ULTRA", "Ultra", "4K maps, 1024 x 1024 mesh. Hero close-ups; takes a while", 3),
]


def biome_items(self, context):
    items = [("AUTO", "Preset Default", "Use the biome the landform was designed for", "AUTO", 0)]
    items += [(b.id, b.label, b.description, "NONE", i + 1) for i, b in enumerate(biomes.BIOMES)]
    _items_cache["biomes"] = items
    return items


def _preset_items(self, context):
    items = []
    for i, p in enumerate(x for x in presets.PRESETS if x.category == self.category):
        icon = thumbs.icon(f"T_{p.id}") or presets.CATEGORY_ICON[p.category]
        items.append((p.id, p.label, p.description, icon, i))
    _items_cache["presets"] = items
    return items


def _horizon_items(self, context):
    items = [(h[0], h[1], h[2], thumbs.icon(f"T_{h[0]}") or "WORLD", i) for i, h in enumerate(presets.HORIZONS)]
    _items_cache["horizons"] = items
    return items


def _category_update(self, context):
    first = next(p for p in presets.PRESETS if p.category == self.category)
    self.preset = first.id


def _preset_update(self, context):
    p = presets.PRESET_BY_ID[self.preset]
    self.size = p.size
    self.height = p.height


def _horizon_update(self, context):
    self.horizon_height = presets.HORIZON_BY_ID[self.horizon_style][4]


class SM_SceneProps(bpy.types.PropertyGroup):
    category: EnumProperty(name="Category", items=[c[:4] + (i,) for i, c in enumerate(presets.CATEGORIES)],
                           update=_category_update)
    preset: EnumProperty(name="Landform", items=_preset_items, update=_preset_update)
    biome: EnumProperty(name="Biome", items=biome_items, description="How the terrain is dressed")
    quality: EnumProperty(name="Quality", items=QUALITY_ITEMS, default="MEDIUM")
    seed: IntProperty(name="Seed", default=0, min=0, description="Each seed gives a different terrain")
    size: FloatProperty(name="Size", default=4000.0, min=10.0, soft_max=50000.0, unit="LENGTH",
                        description="Width of the terrain")
    height: FloatProperty(name="Height", default=1600.0, min=1.0, soft_max=8000.0, unit="LENGTH",
                          description="Height from the base to the highest peak")
    erosion: FloatProperty(name="Erosion", default=1.0, min=0.0, soft_max=3.0,
                           description="How much rain has carved the terrain")
    forests: BoolProperty(name="Forests", default=True, description="Grow the biome's trees on the terrain")
    water: BoolProperty(name="Water", default=True, description="Add water for landforms that have it")
    surroundings: BoolProperty(name="Surroundings", default=True,
                               description="Extend the terrain with low hills out to twice its width, "
                                           "so shots from inside it never show an edge")
    distant: BoolProperty(name="Distant Mountains", default=True,
                          description="Add a ring of distant mountains in the same biome around the terrain")
    frame: BoolProperty(name="Frame a Shot", default=False,
                        description="Aim the scene camera at the summit from inside the landscape")

    horizon_style: EnumProperty(name="Style", items=_horizon_items, update=_horizon_update)
    horizon_biome: EnumProperty(name="Biome", items=biome_items)
    horizon_radius: FloatProperty(name="Distance", default=4000.0, min=10.0, soft_max=100000.0, unit="LENGTH",
                                  description="Distance from the centre to the foot of the mountains")
    horizon_depth: FloatProperty(name="Depth", default=3000.0, min=10.0, soft_max=50000.0, unit="LENGTH",
                                 description="How far back the mountains reach")
    horizon_height: FloatProperty(name="Height", default=1400.0, min=1.0, soft_max=10000.0, unit="LENGTH",
                                  description="Height of the highest peak")
    horizon_seed: IntProperty(name="Seed", default=0, min=0)
    horizon_quality: EnumProperty(name="Quality", items=QUALITY_ITEMS, default="MEDIUM")


def register():
    bpy.utils.register_class(SM_SceneProps)
    bpy.types.Scene.summit = PointerProperty(type=SM_SceneProps)


def unregister():
    del bpy.types.Scene.summit
    bpy.utils.unregister_class(SM_SceneProps)
