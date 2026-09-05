# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Submit selected moodboard images/videos to catalogued video generation."""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_video_gen_generate(Operator):
    """Generate a video from a prompt and selected moodboard references"""

    bl_idname = "mixie.video_gen_generate"
    bl_label = "Generate Video"
    bl_description = "Generate a Seedance video from text and selected references"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params,
            resolve_model_slug,
            resolve_service_key,
        )
        from mixar.modules.moodboard.core.media_utils import (
            get_selected_moodboard_media_inputs,
        )

        sidebar = getattr(context.scene, "mixie_moodboard_sidebar", None)
        tab = getattr(sidebar, "tab_video_gen", None) if sidebar else None
        if tab is None:
            self.report({'ERROR'}, "Video Gen tab is unavailable")
            return {'CANCELLED'}

        prompt = str(getattr(tab, "prompt", "") or "").strip()
        if not prompt:
            self.report({'WARNING'}, "Enter a video prompt")
            return {'CANCELLED'}

        service_key = resolve_service_key(
            "video_gen", getattr(tab, "mode", "")
        )
        if service_key != "video_gen":
            self.report({'ERROR'}, "The selected video service needs a newer app version")
            return {'CANCELLED'}
        model = resolve_model_slug(service_key, getattr(tab, "model", ""))
        if not model:
            self.report({'ERROR'}, "No enabled video model is available")
            return {'CANCELLED'}

        refs = get_selected_moodboard_media_inputs(context, fresh=True)
        from mixar.modules.moodboard.core.video_generation_catalog import (
            build_image_reference_inputs,
            build_video_reference_inputs,
            get_video_generation_limits,
            seedance_reference_count_error,
        )

        limits = get_video_generation_limits(service_key)
        if limits is None:
            self.report({'ERROR'}, "Video generation catalog config is incomplete")
            return {'CANCELLED'}

        params = collect_params(service_key, model)
        count_error = seedance_reference_count_error(
            limits,
            image_count=len(refs["images"]),
            video_count=len(refs["videos"]),
            image_mode=(params or {}).get("image_mode"),
        )
        if count_error:
            self.report({'WARNING'}, count_error)
            return {'CANCELLED'}
        if not refs["all_video_sources_available"]:
            self.report({'ERROR'}, "A selected video was moved or deleted")
            return {'CANCELLED'}

        try:
            video_inputs = build_video_reference_inputs(refs["videos"], limits)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        image_inputs = []
        try:
            from mixar.modules.common.utils.image_utils import compress_for_service

            image_inputs = build_image_reference_inputs(
                refs["images"], limits, compress_for_service
            )
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            logger.exception("Could not prepare Seedance image references")
            self.report({'ERROR'}, f"Could not prepare image references: {exc}")
            return {'CANCELLED'}

        try:
            from mixar.modules.common.job_queue import enqueue_generation
            from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_GEN

            job = enqueue_generation(
                kind="video",
                feature_key=FEATURE_VIDEO_GEN,
                job_type=service_key,
                model=model,
                payload={"prompt": prompt, "params": params},
                label=f"VideoGen: {prompt[:40]}",
                display_label=prompt[:40],
                origin_capability_key="video_gen",
                fail_message="Video generation failed",
                prompt_text=prompt,
                image_inputs=image_inputs,
                video_inputs=video_inputs,
                max_video_duration_seconds=limits["max_video_seconds"],
                scene_flag="mixie_video_gen_is_generating",
                batch_popup_title="Video Generation Complete",
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to start video generation: {exc}")
            return {'CANCELLED'}
        if job is None:
            self.report({'WARNING'}, "A duplicate video generation is already queued")
            return {'CANCELLED'}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued

        mark_enqueued(FEATURE_VIDEO_GEN)
        self.report({'INFO'}, "Added video generation to queue")
        return {'FINISHED'}


classes = (MIXIE_OT_video_gen_generate,)
