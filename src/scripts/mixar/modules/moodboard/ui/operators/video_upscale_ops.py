# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Submit the selected moodboard video to catalogued video upscaling."""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_video_upscale_generate(Operator):
    """Upscale the selected moodboard video to 1080p, 2K or 4K"""

    bl_idname = "mixie.video_upscale_generate"
    bl_label = "Upscale Video"
    bl_description = "Upscale the selected moodboard video with FLUX Video Upscale"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from mixar.modules.common.generation_params import collect_params
        from mixar.modules.moodboard.core.media_utils import (
            get_selected_moodboard_video_inputs,
        )
        from mixar.modules.moodboard.core.video_upscale_enqueue import (
            enqueue_video_upscale,
            prepare_video_upscale_source,
            resolve_video_upscale_target,
        )

        sidebar = getattr(context.scene, "mixie_moodboard_sidebar", None)
        tab = getattr(sidebar, "tab_video_upscale", None) if sidebar else None
        if tab is None:
            self.report({'ERROR'}, "Video Upscale tab is unavailable")
            return {'CANCELLED'}

        try:
            service_key, model = resolve_video_upscale_target(
                getattr(tab, "mode", ""), getattr(tab, "model", "")
            )
            # fresh=True: the submit path re-stats the source; the drawer
            # accepts the short-TTL cache.
            selection = get_selected_moodboard_video_inputs(context, fresh=True)
            video_input, limits = prepare_video_upscale_source(selection["videos"])
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        params = collect_params(service_key, model)
        try:
            job = enqueue_video_upscale(
                service_key=service_key,
                model=model,
                prompt=getattr(tab, "prompt", ""),
                params=params,
                video_input=video_input,
                limits=limits,
                scene_flag="mixie_video_upscale_is_generating",
            )
        except Exception as exc:
            logger.exception("Could not start video upscale")
            self.report({'ERROR'}, f"Failed to start video upscale: {exc}")
            return {'CANCELLED'}
        if job is None:
            self.report({'WARNING'}, "A duplicate video upscale is already queued")
            return {'CANCELLED'}

        from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_UPSCALE
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued

        mark_enqueued(FEATURE_VIDEO_UPSCALE)
        self.report({'INFO'}, "Added video upscale to queue")
        return {'FINISHED'}


classes = (MIXIE_OT_video_upscale_generate,)
