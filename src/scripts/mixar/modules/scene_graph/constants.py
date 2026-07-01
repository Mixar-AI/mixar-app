# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the scene_graph module."""

# Scene property (registered on bpy.types.Scene, SKIP_SAVE) holding the
# serialized per-scene graph JSON. Per-scene + runtime-only.
SCENE_GRAPH_PROP = "mixar_scene_graph"

# Scene property holding the JSON result of the most recent query operator call,
# so bpy.ops callers can read it back. Per-scene + runtime-only.
SCENE_GRAPH_RESULT_PROP = "mixar_scene_graph_result"

SCHEMA = "mixar.scene_graph"
VERSION = 5

# Hierarchy (ObjectGraph) relation vocabulary. Layer-local ids.
REL_PARENT_OF = 1
RELATION_TYPES = {
    REL_PARENT_OF: "parent_of",
}
