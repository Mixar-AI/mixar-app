# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-scene property holding the serialized scene graph.

SKIP_SAVE => runtime-only (never written to the .blend); maxlen omitted (0)
=> no size cap, so large scenes serialize fine. Per-scene because it lives on
each bpy.types.Scene instance.
"""

import bpy
from bpy.props import StringProperty

from ..constants import SCENE_GRAPH_PROP, SCENE_GRAPH_RESULT_PROP


def register():
    setattr(bpy.types.Scene, SCENE_GRAPH_PROP, StringProperty(
        name="Mixar Scene Graph",
        description="Per-scene agent-readable scene graph (JSON). Runtime-only.",
        default="",
        options={'SKIP_SAVE'},
    ))
    setattr(bpy.types.Scene, SCENE_GRAPH_RESULT_PROP, StringProperty(
        name="Mixar Scene Graph Query Result",
        description="JSON result of the last scene-graph query operator call.",
        default="",
        options={'SKIP_SAVE'},
    ))


def unregister():
    for prop in (SCENE_GRAPH_RESULT_PROP, SCENE_GRAPH_PROP):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
