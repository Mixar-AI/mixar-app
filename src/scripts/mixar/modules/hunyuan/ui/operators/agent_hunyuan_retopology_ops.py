# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Hunyuan Retopology Operator

Simplified operator for agent-driven mesh retopology via the Hunyuan 3D
Topology pipeline. The operator validates inputs, applies them to the
existing TopologyProps, and dispatches the standard hunyuan_generate
operator so the entire export/submit/poll/download/import flow is
reused unchanged.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


_POLYGON_TYPE_ALIASES = {
    "quad": "quadrilateral",
    "quads": "quadrilateral",
    "quadrilateral": "quadrilateral",
    "tri": "triangle",
    "triangle": "triangle",
    "triangles": "triangle",
}

_VALID_FACE_LEVELS = {"high", "medium", "low"}


class MIXIE_OT_agent_hunyuan_retopology(Operator):
    """Retopologise the selected high-poly mesh via the agent"""

    bl_idname = "mixie.agent_hunyuan_retopology"
    bl_label = "Agent Hunyuan Retopology"
    bl_description = "Retopologise selected mesh using Hunyuan 3D Topology"
    bl_options = {'REGISTER'}

    polygon_type: StringProperty(
        name="Polygon Type",
        description="Output topology: 'quadrilateral' (or 'quad') or 'triangle'",
        default="quadrilateral",
    )
    face_level: StringProperty(
        name="Face Level",
        description="Output face-count level: 'high', 'medium', or 'low'",
        default="medium",
    )

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, 'hunyuan')

    def execute(self, context):
        if not any(o.type == 'MESH' for o in context.selected_objects):
            self.report({'ERROR'}, "No mesh selected in viewport")
            return {'CANCELLED'}

        poly = _POLYGON_TYPE_ALIASES.get(self.polygon_type.strip().lower())
        if poly is None:
            self.report(
                {'ERROR'},
                f"Invalid polygon_type '{self.polygon_type}'. "
                "Expected 'quadrilateral' or 'triangle'.",
            )
            return {'CANCELLED'}

        face = self.face_level.strip().lower()
        if face not in _VALID_FACE_LEVELS:
            self.report(
                {'ERROR'},
                f"Invalid face_level '{self.face_level}'. "
                "Expected 'high', 'medium', or 'low'.",
            )
            return {'CANCELLED'}

        topo = context.scene.hunyuan.topology
        try:
            topo.polygon_type = poly
            topo.face_level = face
        except Exception as e:
            self.report({'ERROR'}, f"Failed to set topology properties: {e}")
            return {'CANCELLED'}

        # Reuse the existing generate operator (mode_override='TOPOLOGY') so the
        # full submit/poll/download/import pipeline is shared with the UI.
        result = bpy.ops.mixie.hunyuan_generate(mode_override='TOPOLOGY')
        if result != {'FINISHED'}:
            self.report({'ERROR'}, "Hunyuan retopology submission failed")
            return {'CANCELLED'}

        self.report({'INFO'}, "Retopology started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_hunyuan_retopology,)
