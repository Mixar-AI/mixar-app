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

_lookdev_listener = None


def _get_lookdev_listener():
    """Lazily create the lookdev queue listener (cached singleton).

    Replicates the old lookdev_queue.py listener behaviour:
    - on_start: clear error, start progress
    - on_finish: complete progress, redraw all areas
    """
    global _lookdev_listener
    if _lookdev_listener is not None:
        return _lookdev_listener

    from mixar.modules.common.job_queue.core.helpers import (
        create_scene_flag_listener,
    )

    def _on_start(scene):
        try:
            if hasattr(scene, "mixie_lookdev_error"):
                scene.mixie_lookdev_error = ""
        except (AttributeError, TypeError):
            pass
        try:
            from mixar.modules.moodboard.core.generate_progress import (
                start_progress,
            )
            start_progress("lookdev")
        except Exception:
            pass

    def _on_finish(scene):
        try:
            from mixar.modules.moodboard.core.generate_progress import (
                complete_progress,
            )
            complete_progress("lookdev")
        except Exception:
            pass
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    _lookdev_listener = create_scene_flag_listener(
        "mixie_lookdev_is_generating",
        on_start=_on_start,
        on_finish=_on_finish,
    )
    return _lookdev_listener


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

    # Direct invocation property (used by agent scripts).
    prompt: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

        scene = context.scene
        props = _get_lookdev_props(scene)

        # Resolve prompt: direct property → chat override → sidebar → global fallback
        if self.prompt and self.prompt.strip():
            prompt = self.prompt.strip()
        elif self.from_chat:
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
            set_agent_gen_reason(context, "No prompt provided for lookdev")
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Render depth map from scene
        fast_mode = props.fast_mode if props else False
        mode_str = " (fast mode)" if fast_mode else ""
        self.report({'INFO'}, f"Rendering depth map from scene{mode_str}...")
        depth_filepath, success = prepare_depth_render(fast_mode=fast_mode)

        if not success or not depth_filepath:
            set_agent_gen_reason(context, "Failed to render a depth map (needs a scene with visible geometry)")
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
        import base64 as _b64
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_LOOKDEV

        stripped_prompt = prompt.strip()
        payload = {
            "prompt": stripped_prompt,
            "depth_map_bytes_b64": _b64.b64encode(depth_bytes).decode(),
            "params": {},
        }

        job = enqueue_generation(
            kind="image",
            feature_key=FEATURE_LOOKDEV,
            job_type="depth_to_image",
            model="flux-depth-dev",
            payload=payload,
            label=f"Lookdev: {stripped_prompt[:40]}",
            fail_message="Lookdev generation failed",
            name_prefix="lookdev",
            prompt_text=stripped_prompt,
            undo_message="Blockout to Render",
            listener=_get_lookdev_listener(),
        )

        if not job:
            self.report({'ERROR'}, "Failed to enqueue lookdev job")
            return {'CANCELLED'}

        self.report({'INFO'}, "Depth map rendered, generation started...")
        return {'FINISHED'}


classes = (
    MIXIE_OT_lookdev_generate_from_scene,
)
