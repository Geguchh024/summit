# SPDX-License-Identifier: GPL-3.0-or-later
"""Summit: procedural mountains, hills, canyons and horizons, with erosion, biomes and impostor forests."""


def register():
    # imported here so the bpy-free modules (noise, field, recipes, generate) load without Blender
    from . import ops, props, ui
    props.register()
    ops.register()
    ui.register()


def unregister():
    from . import ops, props, thumbs, ui
    ui.unregister()
    thumbs.clear()
    ops.unregister()
    props.unregister()
