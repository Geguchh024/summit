# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview thumbnails for landforms and horizons (rendered by tools/render_thumbnails.py)."""

import os

import bpy.utils.previews

DIR = os.path.join(os.path.dirname(__file__), "thumbs")
_pcoll = None


def _coll():
    global _pcoll
    if _pcoll is None:
        _pcoll = bpy.utils.previews.new()
    return _pcoll


def icon(key):
    """Icon id for thumbs/<key>.png, or 0 when there is no thumbnail."""
    pc = _coll()
    if key in pc:
        return pc[key].icon_id
    path = os.path.join(DIR, key + ".png")
    if not os.path.exists(path):
        return 0
    return pc.load(key, path, "IMAGE").icon_id


def clear():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
