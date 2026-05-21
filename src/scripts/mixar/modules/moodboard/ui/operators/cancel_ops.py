# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Cancel Generation Operators

Generic cancel operator for async-only features (imagegen, lookdev,
lookdev360, image_to_3d) and a specific cancel for Segment to 3D
which uses SceneGenManager.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger
from ...core.generate_progress import reset_progress

logger = get_logger(__name__)


class MIXIE_OT_cancel_generation(Operator):
    """Cancel the current generation — resets flag and progress"""

    bl_idname = "mixie.cancel_generation"
    bl_label = "Cancel"
    bl_description = "Cancel the current generation"
    bl_options = {'REGISTER'}

    tab_prefix: StringProperty(
        name="Tab Prefix",
        description="Progress / flag prefix (e.g. 'imagegen', 'lookdev')",
        default="",
    )

    gen_flag_attr: StringProperty(
        name="Generating Flag",
        description="Override for the is_generating scene attribute",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        scene = context.scene
        prefix = self.tab_prefix
        if not prefix:
            self.report({'WARNING'}, "No tab prefix set")
            return {'CANCELLED'}

        flag_attr = self.gen_flag_attr or f'mixie_{prefix}_is_generating'

        if not getattr(scene, flag_attr, False):
            self.report({'INFO'}, "Nothing to cancel")
            return {'CANCELLED'}

        # Reset the generating flag
        if hasattr(scene, flag_attr):
            setattr(scene, flag_attr, False)

        # Reset progress bar
        reset_progress(prefix)

        # Redraw UI
        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        self.report({'INFO'}, "Generation cancelled")
        return {'FINISHED'}


class MIXIE_OT_cancel_segment_to_3d(Operator):
    """Cancel the active Segment to 3D job"""

    bl_idname = "mixie.cancel_segment_to_3d"
    bl_label = "Cancel"
    bl_description = "Cancel the active segment to 3D generation"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, 'mixie_segment_to_3d_is_generating', False)

    def execute(self, context):
        try:
            from ...core.scene_gen_manager import get_scene_gen_manager

            manager = get_scene_gen_manager()
            cancelled = False
            for image_name in list(manager._active_jobs.keys()):
                if manager.cancel_job(image_name):
                    cancelled = True

            if cancelled:
                self.report({'INFO'}, "Scene generation cancelled")
            else:
                # Fallback: reset UI state even if manager had nothing
                scene = context.scene
                scene.mixie_segment_to_3d_is_generating = False
                reset_progress('segment_to_3d')
                self.report({'INFO'}, "Generation cancelled")

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to cancel: {e}")
            return {'CANCELLED'}


classes = (
    MIXIE_OT_cancel_generation,
    MIXIE_OT_cancel_segment_to_3d,
)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
