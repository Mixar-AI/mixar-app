# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local auto-LOD: apply a Decimate modifier to the active mesh.

Cloud retopology stays the quality path. This is the no-network convenience
Higgsfield ships next to remesh — a ratio slider, one undo step, no upload.
"""

import bpy
from bpy.props import FloatProperty
from bpy.types import Operator


class MIXIE_OT_auto_lod(Operator):
    """Decimate the active mesh to a cheaper stand-in."""

    bl_idname = "mixie.auto_lod"
    bl_label = "Quick LOD"
    bl_description = (
        "Apply a Decimate modifier to the active mesh. "
        "Does not upload or spend credits — for a quality retopo use Retopology"
    )
    bl_options = {"REGISTER", "UNDO"}

    ratio: FloatProperty(
        name="Ratio",
        description="Keep this fraction of faces (0.5 = half)",
        default=0.5,
        min=0.01,
        max=1.0,
        subtype="FACTOR",
    )

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return obj is not None and obj.type == "MESH"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}
        modifier = obj.modifiers.new(name="Mixar LOD", type="DECIMATE")
        modifier.ratio = max(0.01, min(1.0, float(self.ratio)))
        try:
            with context.temp_override(object=obj, active_object=obj):
                bpy.ops.object.modifier_apply(modifier=modifier.name)
        except Exception as error:
            try:
                obj.modifiers.remove(modifier)
            except Exception:
                pass
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Decimated {obj.name} to {self.ratio:.0%} faces")
        return {"FINISHED"}


classes = (MIXIE_OT_auto_lod,)
