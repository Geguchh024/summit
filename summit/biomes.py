# SPDX-License-Identifier: GPL-3.0-or-later
"""Biomes: how a terrain is dressed. Rock, ground cover, snow, forests and water.

A biome is a set of values for the ``SM Terrain Surface`` shader inputs
plus a list of forest layers. Any landform can wear any biome. Altitudes
(``Snow Line``, ``Forest Line``…) are fractions of the terrain height, so a
biome looks right on a 200 m hill and on a 3 km peak alike.
"""

from dataclasses import dataclass, field


@dataclass
class Forest:
    species: str            # trees.SPECIES id
    density: float          # trees per hectare where conditions are ideal
    top: float              # highest altitude (fraction of terrain height); trees thin out toward it
    bottom: float = 0.0     # lowest altitude
    height: float = 16.0    # average tree height in metres
    max_slope: float = 35.0  # degrees


@dataclass
class Biome:
    id: str
    label: str
    description: str
    surface: dict           # SM Terrain Surface input values
    forests: list = field(default_factory=list)
    water: tuple = ("#1d3c45", "#3f7f80")   # deep, shallow


# defaults shared by every biome; each biome overrides what it needs
BASE = {
    "Rock Color": "#7a766f",
    "Rock Color 2": "#9a948a",
    "Rock Streaks": "#46423d",
    "Strata": 0.15,
    "Strata Scale": 22.0,
    "Cracks": 0.5,
    "Scree Color": "#948d82",
    "Ground Color": "#5f7d2b",
    "Ground Color 2": "#8c9a38",
    "Dry Color": "#a39556",
    "Ground Line": 0.55,
    "Ground Max Slope": 36.0,
    "Forest Color": "#2b3a20",
    "Forest Line": 0.45,
    "Snow Color": "#eef2f8",
    "Snow Line": 0.65,
    "Snow Amount": 1.0,
    "Snow Max Slope": 52.0,
    "Snow Dusting": 0.5,
    "Boulders": 0.5,
    "Beach Color": "#b9a888",
    "Ripples": 0.0,
    "Macro Variation": 0.5,
}

BIOMES = [
    Biome("ALPINE", "Alpine", "Grey granite, green pastures, conifer forests and snowy summits", {
        "Ground Line": 0.5, "Ground Max Slope": 38.0, "Snow Line": 0.56, "Snow Max Slope": 60.0,
        "Snow Dusting": 0.7,
    }, [
        Forest("BROADLEAF", 140.0, 0.26, height=17.0),
        Forest("FIR", 260.0, 0.48, height=20.0, max_slope=38.0),
    ]),
    Biome("ARCTIC", "Arctic", "Deep snow down to the valleys, dark rock and sparse firs", {
        "Rock Color": "#4f5257", "Rock Color 2": "#6d7076", "Rock Streaks": "#2c2e31",
        "Ground Color": "#6b6a4c", "Ground Color 2": "#857d5c", "Dry Color": "#8c8266",
        "Ground Line": 0.25, "Forest Line": 0.18, "Snow Line": 0.14, "Snow Amount": 1.25,
        "Snow Max Slope": 58.0, "Snow Color": "#f1f5fb",
    }, [Forest("FIR", 90.0, 0.17, height=12.0)], water=("#13282f", "#2f5f66")),
    Biome("VOLCANIC", "Volcanic", "Black basalt and ash with green lower slopes", {
        "Rock Color": "#353130", "Rock Color 2": "#55504b", "Rock Streaks": "#1b1817",
        "Strata": 0.3, "Strata Scale": 9.0, "Cracks": 0.35, "Scree Color": "#45403c",
        "Ground Color": "#556631", "Ground Color 2": "#6f7a3b", "Dry Color": "#6e6449",
        "Ground Line": 0.3, "Forest Line": 0.22, "Snow Line": 0.86, "Snow Amount": 0.7,
    }, [Forest("BROADLEAF", 160.0, 0.22, height=15.0)], water=("#132a30", "#2d6466")),
    Biome("DOLOMITE", "Dolomite", "Pale layered limestone with orange streaks, meadows and scree", {
        "Rock Color": "#d0c7b6", "Rock Color 2": "#c9a37d", "Rock Streaks": "#7a6b5e",
        "Strata": 0.55, "Strata Scale": 26.0, "Cracks": 0.7, "Scree Color": "#d8d1c4",
        "Ground Color": "#62822c", "Ground Color 2": "#93a03c", "Ground Line": 0.5, "Boulders": 0.8,
        "Forest Line": 0.4, "Snow Line": 0.86, "Snow Amount": 0.6,
    }, [Forest("FIR", 220.0, 0.42, height=20.0)]),
    Biome("MEADOW", "Meadow", "Green rolling grassland with groves of broadleaf trees", {
        "Rock Color": "#8a8173", "Rock Color 2": "#a39a88", "Cracks": 0.3,
        "Ground Color": "#62853a", "Ground Color 2": "#93a24c", "Dry Color": "#a89b5a",
        "Ground Line": 1.2, "Ground Max Slope": 40.0, "Forest Line": 1.2, "Snow Line": 2.0,
    }, [Forest("BROADLEAF", 70.0, 1.2, height=16.0)]),
    Biome("HIGHLAND", "Highland", "Moorland browns and heather with scattered pines", {
        "Rock Color": "#6c6862", "Rock Color 2": "#8a857c", "Rock Streaks": "#3c3a37",
        "Ground Color": "#77703f", "Ground Color 2": "#6a5560", "Dry Color": "#8e7f55",
        "Ground Line": 1.0, "Ground Max Slope": 38.0, "Forest Color": "#2f3624",
        "Forest Line": 0.5, "Snow Line": 0.92, "Snow Amount": 0.35,
    }, [Forest("PINE", 25.0, 0.5, height=15.0)], water=("#1a2a2c", "#3e5a55")),
    Biome("FOREST", "Forest", "Densely wooded hills, conifers and broadleaf", {
        "Ground Color": "#4b672c", "Ground Color 2": "#6b7a39", "Ground Line": 1.2,
        "Ground Max Slope": 40.0, "Forest Color": "#24331c", "Forest Line": 1.2, "Snow Line": 2.0,
    }, [
        Forest("BROADLEAF", 180.0, 0.45, height=18.0, max_slope=40.0),
        Forest("FIR", 320.0, 1.2, bottom=0.25, height=21.0, max_slope=40.0),
    ]),
    Biome("AUTUMN", "Autumn", "Orange and red broadleaf woods among dark firs", {
        "Ground Color": "#7a7438", "Ground Color 2": "#8f7a3c", "Dry Color": "#a2834c",
        "Ground Line": 1.0, "Forest Color": "#4a3320", "Forest Line": 0.7, "Snow Line": 0.85,
        "Snow Amount": 0.5,
    }, [
        Forest("AUTUMN", 220.0, 0.5, height=17.0, max_slope=38.0),
        Forest("FIR", 120.0, 0.7, bottom=0.2, height=20.0),
    ]),
    Biome("CANYON", "Red Canyon", "Banded red sandstone, sandy floors and desert scrub", {
        "Rock Color": "#b0532c", "Rock Color 2": "#d99d64", "Rock Streaks": "#5c3424",
        "Strata": 0.8, "Strata Scale": 30.0, "Cracks": 0.35, "Scree Color": "#a8896a",
        "Ground Color": "#c49e76", "Ground Color 2": "#b98a62", "Dry Color": "#c9a77c",
        "Ground Line": 1.2, "Ground Max Slope": 22.0, "Forest Color": "#5b5a33", "Forest Line": 1.2,
        "Snow Line": 2.0, "Beach Color": "#c7a47f", "Macro Variation": 0.35,
    }, [Forest("SHRUB", 40.0, 1.2, height=3.0, max_slope=25.0)], water=("#2c3b2f", "#5b7a5a")),
    Biome("DESERT", "Desert", "Ochre mesas and buttes over a sandy plain", {
        "Rock Color": "#ad6e40", "Rock Color 2": "#d3a06b", "Rock Streaks": "#6a3e26",
        "Strata": 0.85, "Strata Scale": 24.0, "Cracks": 0.4, "Scree Color": "#b4977a",
        "Ground Color": "#d4b088", "Ground Color 2": "#c79d70", "Dry Color": "#cfae84",
        "Ground Line": 1.2, "Ground Max Slope": 20.0, "Forest Color": "#6a6538", "Forest Line": 1.2,
        "Snow Line": 2.0, "Macro Variation": 0.35,
    }, [Forest("SHRUB", 12.0, 1.2, height=2.5, max_slope=18.0)]),
    Biome("DUNES", "Sand Dunes", "Golden sand with wind ripples", {
        "Rock Color": "#c3935c", "Rock Color 2": "#d8b07a", "Rock Streaks": "#a8794a",
        "Strata": 0.0, "Cracks": 0.0, "Scree Color": "#d0a46c",
        "Ground Color": "#ddb882", "Ground Color 2": "#cfa36b", "Dry Color": "#e2c08c",
        "Ground Line": 1.2, "Ground Max Slope": 90.0, "Forest Line": -1.0, "Snow Line": 2.0,
        "Ripples": 1.0, "Macro Variation": 0.25,
    }, []),
    Biome("BADLANDS", "Badlands", "Striped grey, cream and purple clays, nearly bare", {
        "Rock Color": "#8a7f86", "Rock Color 2": "#c6b8a3", "Rock Streaks": "#584c54",
        "Strata": 1.0, "Strata Scale": 5.0, "Cracks": 0.25, "Scree Color": "#a69a92",
        "Ground Color": "#958f62", "Ground Color 2": "#a69a6c", "Dry Color": "#b0a072",
        "Ground Line": 1.2, "Ground Max Slope": 14.0, "Forest Line": 1.2, "Snow Line": 2.0,
    }, [Forest("SHRUB", 8.0, 1.2, height=2.0, max_slope=12.0)]),
    Biome("NORDIC", "Nordic", "Dark gneiss, mossy slopes, spruce woods and late snow", {
        "Rock Color": "#6b6d6b", "Rock Color 2": "#8a8c86", "Rock Streaks": "#3c3e3e",
        "Ground Color": "#4c6331", "Ground Color 2": "#6c7340", "Ground Line": 0.5,
        "Ground Max Slope": 38.0, "Forest Line": 0.38, "Snow Line": 0.68, "Snow Amount": 0.95,
        "Beach Color": "#6b665b",
    }, [Forest("FIR", 300.0, 0.36, height=18.0, max_slope=40.0)], water=("#0f262c", "#2a5653")),
    Biome("TROPICAL", "Tropical", "Grey limestone draped in dense jungle, sandy shores", {
        "Rock Color": "#86857b", "Rock Color 2": "#a3a196", "Rock Streaks": "#3e4037",
        "Strata": 0.2, "Cracks": 0.4, "Scree Color": "#8e8a7c",
        "Ground Color": "#3d6a29", "Ground Color 2": "#5a8a33", "Dry Color": "#7e8a45",
        "Ground Line": 1.2, "Ground Max Slope": 62.0, "Forest Color": "#1f3a17", "Forest Line": 1.2,
        "Snow Line": 2.0, "Beach Color": "#d9c9a0",
    }, [
        Forest("BROADLEAF", 320.0, 1.2, bottom=0.04, height=19.0, max_slope=60.0),
        Forest("SHRUB", 400.0, 1.2, height=4.0, max_slope=60.0),
    ], water=("#0f4a55", "#3fb4b0")),
]
BIOME_BY_ID = {b.id: b for b in BIOMES}


def surface_values(biome_id):
    values = dict(BASE)
    values.update(BIOME_BY_ID[biome_id].surface)
    return values
