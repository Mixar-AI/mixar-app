# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev Scene Operators

Operator for generating lookdev images from a 3D viewport depth render.
Uses the unified generation queue (depth_to_image job type).
"""

import bpy
from bpy.types import Operator

from ...core.lookdev_utils import prepare_depth_render
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _get_lookdev_props(scene):
    """Get lookdev tab properties from sidebar, with fallback to old properties."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev'):
            return sidebar.tab_lookdev
    return None


class MIXIE_OT_lookdev_generate_from_scene(Operator):
    """Render depth map from scene and generate lookdev images"""

    bl_idname = "mixie.lookdev_generate_from_scene"
    bl_label = "Generate from Scene"
    bl_description = "Render depth map from current scene and generate AI images using Flux Depth"
    bl_options = {'REGISTER'}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use global scene property for prompt",
        default=False,
    )

    def execute(self, context):
        scene = context.scene
        props = _get_lookdev_props(scene)

        # Resolve prompt: chat override → sidebar → global fallback
        if self.from_chat:
            prompt = getattr(scene, 'mixie_lookdev_prompt', '')
        elif props:
            prompt = props.prompt
            if not prompt or not prompt.strip():
                fallback = getattr(scene, 'mixie_lookdev_prompt', '')
                if fallback and fallback.strip():
                    prompt = fallback
        else:
            prompt = getattr(scene, 'mixie_lookdev_prompt', '')

        if not prompt or not prompt.strip():
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Render depth map from scene
        fast_mode = props.fast_mode if props else False
        mode_str = " (fast mode)" if fast_mode else ""
        self.report({'INFO'}, f"Rendering depth map from scene{mode_str}...")
        depth_filepath, success = prepare_depth_render(fast_mode=fast_mode)

        if not success or not depth_filepath:
            self.report({'ERROR'}, "Failed to render depth map")
            return {'CANCELLED'}

        # Compress depth map to bytes for the queue payload
        try:
            from mixar.modules.common.utils.image_utils import compress_file_for_service
            depth_bytes = compress_file_for_service(depth_filepath, "lookdev")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read depth map: {e}")
            return {'CANCELLED'}

        # Clear previous error
        if hasattr(scene, 'mixie_lookdev_error'):
            scene.mixie_lookdev_error = ""

        # Enqueue via the unified generation queue
        from ...core.lookdev_queue import enqueue_lookdev_job

        job = enqueue_lookdev_job(
            prompt=prompt.strip(),
            depth_map_bytes=depth_bytes,
        )

        if not job:
            self.report({'ERROR'}, "Failed to enqueue lookdev job")
            return {'CANCELLED'}

        self.report({'INFO'}, "Depth map rendered, generation started...")
        return {'FINISHED'}


classes = (
    MIXIE_OT_lookdev_generate_from_scene,
)
