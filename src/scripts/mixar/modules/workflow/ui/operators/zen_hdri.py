# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native file selection and undoable environment source changes."""

import bpy
from bpy.props import BoolProperty, StringProperty

from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.zen_scene import sky_enabled
from ...core.zen_sky_lighting import load_hdri, set_sky_source
from ...core.zen_sky_viewports import set_sky_viewports


def _editable(context):
    return (context.scene is not None and context.scene.is_editable
            and context.scene.render.engine in {"CYCLES", "BLENDER_EEVEE"})


class MIXAR_OT_zen_load_hdri(bpy.types.Operator):
    bl_idname = "mixar.zen_load_hdri"
    bl_label = "Add HDRI"
    bl_description = "Load an HDR or EXR environment image and enable Sky Light"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.hdr;*.exr", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _editable(context)

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            restart = not sky_enabled(context.scene)
            load_hdri(context.scene, self.filepath)
            set_sky_viewports(context.scene, True, context.screen, restart=restart)
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            self.report({"ERROR"}, f"Could not load HDRI: {exc}")
            return {"CANCELLED"}
        mark_file_select_executed(self)
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        return {"FINISHED"}


class MIXAR_OT_zen_sky_source(bpy.types.Operator):
    bl_idname = "mixar.zen_sky_source"
    bl_label = "Lighting Source"
    bl_description = "Switch between the procedural sky and the loaded HDRI"
    bl_options = {"REGISTER", "UNDO"}

    hdri: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return _editable(context) and context.scene.mixar_zen_sky.sky_world is not None

    def execute(self, context):
        try:
            set_sky_source(context.scene, self.hdri)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (MIXAR_OT_zen_load_hdri, MIXAR_OT_zen_sky_source)
