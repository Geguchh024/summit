# SPDX-License-Identifier: GPL-3.0-or-later
"""The terrain library: every ready-made landform with its default size, height and biome.

This module does not use bpy, so the preview tools can read it too.
"""

from dataclasses import dataclass

CATEGORIES = [
    ("MOUNTAINS", "Mountains", "Peaks, ranges, massifs and volcanoes", "TRIA_UP"),
    ("HILLS", "Hills", "Rolling hills, highlands and wooded foothills", "IPO_SINE"),
    ("DESERT", "Desert", "Canyons, mesas, dunes and badlands", "SEQ_LUMA_WAVEFORM"),
    ("LANDSCAPES", "Landscapes", "Valleys, fjords, islands and huge vistas", "WORLD"),
]


@dataclass
class Preset:
    id: str
    label: str
    category: str
    description: str
    biome: str
    size: float              # metres across
    height: float            # metres, base to highest peak
    falloff: float = 0.0     # fade to flat at the edges (fraction of the half width)
    water: float = -1.0      # water level as a fraction of the height; -1 for none
    haze: float = 0.08       # aerial haze per kilometre


PRESETS = [
    Preset("ALPINE_PEAK", "Alpine Peak", "MOUNTAINS",
           "A lone pyramidal summit with sharp arêtes, deep gullies and snowfields", "ALPINE", 4000.0, 1600.0,
           falloff=0.25),
    Preset("MOUNTAIN_RANGE", "Mountain Range", "MOUNTAINS",
           "A long eroded ridge of peaks with lower ranges behind", "ALPINE", 6000.0, 1500.0),
    Preset("SNOWY_MASSIF", "Snowy Massif", "MOUNTAINS",
           "A broad, heavily glaciated mountain buried in snow", "ARCTIC", 5000.0, 1400.0, falloff=0.3),
    Preset("VOLCANO", "Volcano", "MOUNTAINS",
           "A stratovolcano with a summit crater and radial gullies", "VOLCANIC", 6000.0, 1700.0, falloff=0.2),
    Preset("DOLOMITES", "Dolomites", "MOUNTAINS",
           "Sheer limestone towers and walls rising over scree and meadows", "DOLOMITE", 3000.0, 900.0),
    Preset("ROLLING_HILLS", "Rolling Hills", "HILLS",
           "Soft green hills with groves of trees", "MEADOW", 2000.0, 160.0),
    Preset("HIGHLANDS", "Highlands", "HILLS",
           "Rugged moorland with rocky tops and boggy hollows", "HIGHLAND", 4000.0, 600.0, water=0.04),
    Preset("FOOTHILLS", "Wooded Foothills", "HILLS",
           "Steep forested hills cut by stream valleys", "FOREST", 3000.0, 550.0),
    Preset("CANYON", "Canyon", "DESERT",
           "A winding river canyon with terraced red walls and side gorges", "CANYON", 3000.0, 450.0, water=0.115),
    Preset("MESAS", "Mesas & Buttes", "DESERT",
           "Flat-topped mesas and lone buttes over a desert plain", "DESERT", 4000.0, 380.0, haze=0.05),
    Preset("DUNES", "Sand Dunes", "DESERT",
           "Rows of wind-sculpted dunes with soft crests", "DUNES", 3000.0, 120.0, haze=0.05),
    Preset("BADLANDS", "Badlands", "DESERT",
           "Striped clay hills carved into dense gullies", "BADLANDS", 1500.0, 160.0),
    Preset("VALLEY", "Glacial Valley", "LANDSCAPES",
           "A U-shaped valley between high ridges, made for hero shots", "ALPINE", 5000.0, 1500.0),
    Preset("VAST", "Vast Landscape", "LANDSCAPES",
           "Mountains, hills and river valleys over many kilometres", "ALPINE", 12000.0, 1800.0, haze=0.1),
    Preset("FJORD", "Fjord", "LANDSCAPES",
           "Steep mountains plunging into winding sea inlets", "NORDIC", 6000.0, 1300.0, water=0.14),
    Preset("KARST", "Karst Towers", "LANDSCAPES",
           "Jungle-covered limestone towers over flooded plains", "TROPICAL", 3000.0, 380.0, water=0.035),
    Preset("ARCHIPELAGO", "Archipelago", "LANDSCAPES",
           "Wooded islands with beaches in a shallow sea", "TROPICAL", 5000.0, 450.0, water=0.3),
]
PRESET_BY_ID = {p.id: p for p in PRESETS}
CATEGORY_ICON = {c[0]: c[3] for c in CATEGORIES}

# horizon ring styles: shape recipe, default biome, height
HORIZONS = [
    ("H_PEAKS", "Alpine Peaks", "Jagged snowy peaks all around", "ALPINE", 1400.0),
    ("H_SNOW", "Snowy Range", "Massive glaciated mountains", "ARCTIC", 1600.0),
    ("H_HILLS", "Rolling Hills", "Low green hills on the horizon", "MEADOW", 300.0),
    ("H_MESAS", "Desert Mesas", "Flat-topped mesas on a desert horizon", "DESERT", 450.0),
]
HORIZON_BY_ID = {h[0]: h for h in HORIZONS}
