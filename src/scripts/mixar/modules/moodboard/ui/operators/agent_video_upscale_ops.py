# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Video Upscale Operator.

Agent-driven entry point for FLUX Video Upscale. Unlike the interactive
``mixie.video_upscale_generate`` (which reads the Video Upscale tab + the
moodboard selection), this takes ONE explicit ``video_name`` (a moodboard
movie by datablock name) plus optional ``prompt`` / ``model`` and the model's
catalog ``params`` as one JSON string, and dispatches through the SAME
``prepare_video_upscale_source`` / ``enqueue_video_upscale`` path the tab and
the canvas node use — so source ceilings, the upload ``purpose`` and the
single ``video_s3_key`` payload shape are all shared.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason and
return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _fail(context, reason: str):
    """Record the reason for the agent and cancel."""
    from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

    set_agent_gen_reason(context, reason)
    return {'CANCELLED'}


class MIXIE_OT_agent_video_upscale(Operator):
    """Upscale one named moodboard video to 1080p, 2K or 4K (agent entry)"""

    bl_idname = "mixie.agent_video_upscale"
    bl_label = "Agent Video Upscale"
    bl_description = "Upscale the named moodboard video with FLUX Video Upscale"
    bl_options = {'REGISTER'}

    video_name: StringProperty(
        name="Video",
        description="bpy.data.images name of the moodboard movie to upscale",
        default="",
    )
    prompt: StringProperty(
        name="Prompt",
        description="Optional guidance for the upscale",
        default="",
    )
    model: StringProperty(
        name="Model Slug",
        description="Model slug from the catalog (empty = catalog default)",
        default="",
    )
    params: StringProperty(
        name="Parameters",
        description="The model's catalog parameters as a JSON object",
        default="",
    )

    def execute(self, context):
        from mixar.bootstrap.generation_catalog_cache import (
            get_default_model_slug,
            get_model,
        )
        from mixar.modules.common.utils.agent_feedback import clear_agent_gen_reason
        from mixar.modules.moodboard.core.agent_video import (
            find_moodboard_media,
            merge_catalog_params,
            resolve_agent_model,
        )
        from mixar.modules.moodboard.core.media_utils import describe_moodboard_media
        from mixar.modules.moodboard.core.video_upscale_catalog import SERVICE_KEY
        from mixar.modules.moodboard.core.video_upscale_enqueue import (
            enqueue_video_upscale,
            prepare_video_upscale_source,
        )

        clear_agent_gen_reason(context)
        name = (self.video_name or "").strip()
        if not name:
            return _fail(context, "video_name is required for video upscale")

        try:
            model = resolve_agent_model(
                SERVICE_KEY, self.model,
                get_model=get_model, get_default=get_default_model_slug,
            )
            videos = find_moodboard_media(
                context.scene, [name],
                describe=describe_moodboard_media, want_video=True,
            )
            # The same source checks the tab runs: count, extension, size,
            # duration, frame size — before anything uploads.
            video_input, limits = prepare_video_upscale_source(videos)
            params = merge_catalog_params(get_model(SERVICE_KEY, model), self.params)
        except ValueError as exc:
            return _fail(context, str(exc))

        try:
            job = enqueue_video_upscale(
                service_key=SERVICE_KEY,
                model=model,
                prompt=self.prompt,
                params=params,
                video_input=video_input,
                limits=limits,
                scene_flag="mixie_video_upscale_is_generating",
            )
        except Exception as exc:
            logger.exception("Could not start agent video upscale")
            return _fail(context, f"Failed to start video upscale: {exc}")
        if job is None:
            return _fail(context, "A duplicate video upscale is already queued")

        try:
            from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_UPSCALE
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
                mark_enqueued,
            )

            mark_enqueued(FEATURE_VIDEO_UPSCALE)
        except Exception:
            pass

        self.report({'INFO'}, "Video upscale started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_video_upscale,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
