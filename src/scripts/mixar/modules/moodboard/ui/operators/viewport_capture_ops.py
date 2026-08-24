# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture the 3D viewport onto the moodboard as a generation reference."""

from bpy.types import Operator

from mixar.modules.moodboard.core.viewport_capture import capture_viewport_to_board


class MIXIE_OT_moodboard_capture_viewport(Operator):
    """Pack an OpenGL still of the 3D view onto the moodboard and select it."""

    bl_idname = "mixie.moodboard_capture_viewport"
    bl_label = "Capture Viewport"
    bl_description = (
        "Capture the current 3D viewport as a moodboard still and select it "
        "so Generate tabs that use the selected image pick it up"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            item = capture_viewport_to_board(context)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        name = getattr(getattr(item, "image", None), "name", "Viewport")
        self.report({"INFO"}, f"Captured {name} to the moodboard")
        return {"FINISHED"}


classes = (MIXIE_OT_moodboard_capture_viewport,)
