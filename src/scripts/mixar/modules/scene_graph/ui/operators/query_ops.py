# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operator the agent calls to fetch / traverse the per-scene scene graph.

    bpy.ops.mixar.scene_graph_query(tool="scene_graph_summary", params="{}")
    bpy.ops.mixar.scene_graph_query(tool="children",
                                    params='{"object_name": "Cargo_Crates_on_Pallet_Root"}')

The JSON result is written to scene.mixar_scene_graph_result (read it back after
the call) and also printed with the __RESULT__ marker so the agent's script
executor can capture it. Operates on the operator's context scene -> per-scene.
"""

import json

import bpy
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger
from mixar.modules.scene_graph.constants import SCENE_GRAPH_RESULT_PROP
from mixar.modules.scene_graph.core.tools import run_tool

logger = get_logger(__name__)


class MIXAR_OT_scene_graph_query(bpy.types.Operator):
    bl_idname = "mixar.scene_graph_query"
    bl_label = "Query Scene Graph"
    bl_description = "Fetch or traverse the per-scene scene graph"
    bl_options = {'INTERNAL'}

    tool: StringProperty(
        name="Tool",
        description="get_graph | scene_graph_summary | roots | children | "
                    "descendants | ancestors | describe_object",
        default="scene_graph_summary",
    )
    params: StringProperty(
        name="Params (JSON)",
        description='JSON object of tool arguments, e.g. {"object_name": "Foo"}',
        default="{}",
    )

    def execute(self, context):
        scene = context.scene
        try:
            params = json.loads(self.params) if self.params else {}
            if not isinstance(params, dict):
                raise ValueError("params must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            result = {"error": f"invalid params: {exc}"}
        else:
            result = run_tool(scene, self.tool, params)

        payload = json.dumps(result)
        if hasattr(scene, SCENE_GRAPH_RESULT_PROP):
            setattr(scene, SCENE_GRAPH_RESULT_PROP, payload)
        # Marker for the agent script executor to capture.
        print("__RESULT__" + payload)

        if isinstance(result, dict) and "error" in result:
            self.report({'WARNING'}, f"scene_graph: {result['error']}")
        else:
            self.report({'INFO'}, f"scene_graph: {self.tool} ok")
        return {'FINISHED'}


classes = (MIXAR_OT_scene_graph_query,)
