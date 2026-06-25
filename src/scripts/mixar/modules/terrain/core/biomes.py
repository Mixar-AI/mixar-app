# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Biome Registry — ecological scatter rules

Maps a biome to an ordered list of vegetation layers. Each layer's ``density`` is a
function of the ecological masks (distw, moisture, haw, slope, under) computed by
masks.py, returning a 0..1 per-vertex factor that the GN scatter multiplies by
``max_density`` (instances/m²). This is where "correct semantics" lives — riprap at
the bank toe, grass by moisture, wildflowers above it, trees set back. Density formulas
are ported from the validated /tmp/bq_riparian.py prototype.

Layer: {id, asset, max_density, scale (min,max), align (to surface normal), density(m)}.
``m`` is a dict of numpy arrays: distw, moisture, haw, slope, under (0/1 float).
"""


def _f(a):
    return a.astype("f4")


# Riparian succession: water -> riprap toe -> grass/flower bank -> meadow -> tree line.
RIPARIAN = [
    {"id": "pebble", "asset": "pebble", "max_density": 11.0, "scale": (1.2, 2.4), "align": True,
     "density": lambda m: _f(((m["distw"] > 0.8) & (m["distw"] < 2.9))
                             & (m["haw"] > -0.15) & (m["haw"] < 0.6) & (m["under"] < 0.5))},
    {"id": "grass", "asset": "grass", "max_density": 9.0, "scale": (0.6, 1.3), "align": True,
     "density": lambda m: _f(m["moisture"] * ((m["haw"] > 0.15) & (m["haw"] < 3.5)) * (m["under"] < 0.5))},
    {"id": "fern", "asset": "fern", "max_density": 0.8, "scale": (0.7, 1.2), "align": False,
     "density": lambda m: _f(m["moisture"] * ((m["haw"] > 0.1) & (m["haw"] < 1.2)) * (m["under"] < 0.5))},
    {"id": "daisy", "asset": "daisy", "max_density": 1.1, "scale": (0.7, 1.3), "align": False,
     "density": lambda m: _f(m["moisture"] * ((m["haw"] > 0.25) & (m["haw"] < 2.0)) * (m["under"] < 0.5))},
    {"id": "dandelion", "asset": "dandelion", "max_density": 0.7, "scale": (0.7, 1.3), "align": False,
     "density": lambda m: _f(m["moisture"] * ((m["haw"] > 0.3) & (m["haw"] < 2.0)) * (m["under"] < 0.5))},
    {"id": "tree", "asset": "tree_deciduous", "max_density": 0.03, "scale": (0.7, 1.15), "align": False,
     "density": lambda m: _f((m["distw"] > 8.0) & (m["haw"] > 1.0) & (m["under"] < 0.5))},
]

# Lush alpine/temperate meadow with a sparse tree line on the higher, drier ground.
MEADOW = [
    {"id": "grass", "asset": "grass", "max_density": 10.0, "scale": (0.6, 1.3), "align": True,
     "density": lambda m: _f((0.4 + 0.6 * m["moisture"]) * (m["slope"] < 0.5) * (m["under"] < 0.5))},
    {"id": "daisy", "asset": "daisy", "max_density": 1.4, "scale": (0.7, 1.3), "align": False,
     "density": lambda m: _f((0.5 + 0.5 * m["moisture"]) * (m["slope"] < 0.4) * (m["under"] < 0.5))},
    {"id": "shrub", "asset": "shrub", "max_density": 0.06, "scale": (0.8, 1.3), "align": False,
     "density": lambda m: _f((m["slope"] < 0.45) * (m["under"] < 0.5))},
    {"id": "tree", "asset": "tree_deciduous", "max_density": 0.02, "scale": (0.8, 1.2), "align": False,
     "density": lambda m: _f((m["haw"] > 1.5) * (m["slope"] < 0.4) * (m["under"] < 0.5))},
]

# Coniferous forest floor on gentler ground; bare rock/scree on steep slopes.
FOREST = [
    {"id": "grass_dry", "asset": "grass_dry", "max_density": 6.0, "scale": (0.6, 1.2), "align": True,
     "density": lambda m: _f((m["slope"] < 0.4) * (m["under"] < 0.5))},
    {"id": "fern", "asset": "fern", "max_density": 1.5, "scale": (0.7, 1.3), "align": False,
     "density": lambda m: _f((0.3 + 0.7 * m["moisture"]) * (m["slope"] < 0.45) * (m["under"] < 0.5))},
    {"id": "rock", "asset": "rock", "max_density": 0.05, "scale": (0.5, 1.4), "align": True,
     "density": lambda m: _f((m["slope"] > 0.45) * (m["under"] < 0.5))},
    {"id": "tree", "asset": "tree_conifer", "max_density": 0.06, "scale": (0.8, 1.3), "align": False,
     "density": lambda m: _f((m["slope"] < 0.45) * (m["under"] < 0.5))},
]

BIOMES = {
    "riparian": RIPARIAN,
    "meadow": MEADOW,
    "forest": FOREST,
}

# Max instances per layer (by layer id). The scatter scales each layer's density down
# so total instances never exceed this — bounding the scene at ANY terrain size so a
# large terrain can't freeze the real-time viewport. Trees are ~283k polys EACH, so
# their budget is tiny; grass/flowers are light, so theirs is larger.
LAYER_BUDGET = {
    "pebble": 1500, "rock": 300,
    "grass": 1800, "grass_dry": 1500,
    "fern": 600, "daisy": 800, "dandelion": 500, "shrub": 120,
    "tree": 18, "sapling": 200,
}
DEFAULT_BUDGET = 700

