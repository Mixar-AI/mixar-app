# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Terrain Module Constants

Semantic presets, biome palettes, and the shared node-group / material names the
terrain engine builds and the operators drive.
"""

# Names of the reusable datablocks the engine builds (get-or-create by name).
MASTER_TERRAIN = "MasterTerrain"
TERRAIN_MATERIAL = "TerrainMaterial"

# ============================================================================
# SEMANTIC PRESETS  (text intent -> MasterTerrain GN input values)
# height_scale = metres of heightmap relief (used once a heightmap is plugged in);
# detail = metres of PROCEDURAL relief (the main text-path knob);
# detail_scale = feature cycles across the terrain; warp = ridgeline distortion.
# ============================================================================
PRESETS = {
    "mountains": {"height_scale": 140.0, "detail": 90.0, "detail_scale": 2.0, "warp": 0.6, "water_level": 0.0, "seed": 0, "biome": "alpine"},
    "hills":     {"height_scale": 50.0,  "detail": 22.0, "detail_scale": 3.0, "warp": 0.4, "water_level": 0.0, "seed": 0, "biome": "verdant"},
    "canyon":    {"height_scale": 90.0,  "detail": 70.0, "detail_scale": 1.5, "warp": 0.3, "water_level": 0.0, "seed": 0, "biome": "desert"},
    "desert":    {"height_scale": 30.0,  "detail": 16.0, "detail_scale": 4.0, "warp": 0.9, "water_level": 0.0, "seed": 0, "biome": "desert"},
    "flat":      {"height_scale": 0.0,   "detail": 1.5,  "detail_scale": 2.0, "warp": 0.2, "water_level": 0.0, "seed": 0, "biome": "verdant"},
}

# ============================================================================
# BIOME PALETTES  (TerrainMaterial zoning: grass=low/flat, low=midslope sediment,
# rock=cliff, snow=peak)
# ============================================================================
BIOMES = {
    "alpine":  {"grass": (0.06, 0.15, 0.05), "low": (0.12, 0.13, 0.08), "rock": (0.20, 0.19, 0.18), "snow": (0.93, 0.95, 0.98)},
    "verdant": {"grass": (0.07, 0.20, 0.04), "low": (0.10, 0.16, 0.05), "rock": (0.22, 0.20, 0.16), "snow": (0.55, 0.60, 0.55)},
    "desert":  {"grass": (0.55, 0.42, 0.22), "low": (0.62, 0.48, 0.28), "rock": (0.45, 0.32, 0.22), "snow": (0.80, 0.70, 0.55)},
}

# create_terrain preset key -> GN socket display name (ordered for reporting).
INPUT_PAIRS = (
    ("Height Scale", "height_scale"), ("Detail", "detail"),
    ("Detail Scale", "detail_scale"), ("Warp", "warp"),
    ("Water Level", "water_level"), ("Seed", "seed"),
)

# accepted set_inputs key (snake_case) -> GN socket display name.
INPUT_NAMES = {
    "height_scale": "Height Scale", "detail": "Detail", "detail_scale": "Detail Scale",
    "warp": "Warp", "water_level": "Water Level", "seed": "Seed",
}
