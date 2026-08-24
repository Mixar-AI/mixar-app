# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply a selected moodboard still as the scene world environment."""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core.world_hdri import (
    apply_image_as_world,
    selected_still_image,
)


class MIXIE_OT_moodboard_apply_as_world(Operator):
    """Set the selected moodboard still as the world HDRI."""

    bl_idname = "mixie.moodboard_apply_as_world"
    bl_label = "Apply as World HDRI"
    bl_description = (
        "Use the selected still as the scene environment map "
        "(equirectangular panoramas work best)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return selected_still_image(context) is not None

    def execute(self, context):
        image = selected_still_image(context)
        try:
            apply_image_as_world(image)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"World environment set to {image.name}")
        return {"FINISHED"}


classes = (MIXIE_OT_moodboard_apply_as_world,)
