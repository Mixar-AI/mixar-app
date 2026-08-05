# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the selection_assist module (selection autocomplete).

The ghost-outline bridge contract is shared with the C++ overlay engine
(src/source/blender/draw/engines/overlay/overlay_instance.cc): the scene
string property GHOST_PROP holds the names of objects to draw with the
"suggested" outline category, joined by GHOST_SEP. Keep both sides in
sync when changing either.
"""

# -- Python -> C++ ghost outline bridge -------------------------------------
# Scene StringProperty read by the overlay engine each sync. SKIP_SAVE —
# suggestions are transient UI state and must never persist in .blend files.
GHOST_PROP = "mixar_suggested_outline"
# Separator for object names inside GHOST_PROP. Unit Separator control char:
# cannot appear in datablock names, same convention as the chat Enter-submit
# marker.
GHOST_SEP = "\x1f"
# Never ghost-outline more objects than this — a suggestion covering half the
# scene is noise, and the string property should stay small.
MAX_GHOST_OBJECTS = 400

# -- Engine ------------------------------------------------------------------
# WindowManager toggle (not persisted) to disable the whole feature.
ENABLE_PROP = "mixar_selection_assist_enabled"
# Selection-hash poll cadence. Selection changes are only *detected* here;
# all heavy work stays lazy behind hash/dirty checks.
POLL_INTERVAL = 0.25
# Levels whose object count exceeds this are dropped from the ladder.
MAX_LEVEL_OBJECTS = 400

# -- Grouping heuristics -------------------------------------------------------
# Tokens stripped from object names when deriving the semantic "stem" used to
# group sibling parts (Stool_Leg_Front_Left / Stool_Leg_Rear_Right -> stool leg).
STEM_DROP_TOKENS = frozenset({
    "left", "right", "front", "rear", "back", "top", "bottom",
    "upper", "lower", "mid", "middle", "center", "centre",
    "inner", "outer", "l", "r", "f", "b", "a",
})
# Dimensions are rounded to this many decimals (meters) before signature
# comparison — absorbs float noise between mirrored/duplicated parts.
DIM_ROUND_DECIMALS = 3
# Only geometry objects take part in same-part matching. Empties (asset
# roots!), cameras, lights etc. all share degenerate signatures — without
# this gate every asset root "matches" every other root in the scene.
GEOMETRY_TYPES = frozenset({
    "MESH", "CURVE", "CURVES", "SURFACE", "META", "FONT",
    "POINTCLOUD", "VOLUME", "GREASEPENCIL", "GPENCIL",
})

# -- Hint chip (POST_PIXEL overlay) -------------------------------------------
CHIP_BG_COLOR = (0.086, 0.098, 0.094, 0.92)
CHIP_BORDER_COLOR = (0.290, 0.870, 0.502, 0.85)  # Mixar agent green
CHIP_TEXT_COLOR = (0.92, 0.96, 0.93, 1.0)
CHIP_KEY_COLOR = (0.290, 0.870, 0.502, 1.0)
CHIP_FONT_SIZE = 12
CHIP_PAD_X = 12
CHIP_PAD_Y = 7
CHIP_RADIUS = 6
CHIP_MARGIN_BOTTOM = 22
