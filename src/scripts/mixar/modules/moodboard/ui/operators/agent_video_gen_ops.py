# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Video Generation Operator.

Agent-driven entry point for catalogued video generation (Seedance 2.5, the
MiniMax H3 tiers). Unlike the interactive ``mixie.video_gen_generate`` (which
reads the Video Gen tab + the moodboard selection), this takes an explicit
``prompt`` plus optional ``model``, comma-separated ``reference_image_names``
/ ``reference_video_names`` (moodboard stills / movies by datablock name — a
finished ``render_scene_video`` result is a movie) and the model's catalog
``params`` as one JSON string, and dispatches ONE ``video_gen`` job through
the SAME limits, validators and ``enqueue_generation`` path the tab uses.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason and
return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

SERVICE_KEY = "video_gen"


def _fail(context, reason: str):
    """Record the reason for the agent and cancel."""
    from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

    set_agent_gen_reason(context, reason)
    return {'CANCELLED'}


class MIXIE_OT_agent_video_generate(Operator):
    """Generate a video from a prompt and named moodboard references (agent entry)"""

    bl_idname = "mixie.agent_video_generate"
    bl_label = "Agent Video Generation"
    bl_description = "Generate a video from text and named moodboard references"
    bl_options = {'REGISTER'}

    prompt: StringProperty(
        name="Prompt",
        description="What the video should show or how the references change",
        default="",
    )
    model: StringProperty(
        name="Model Slug",
        description="Model slug from the catalog (empty = catalog default)",
        default="",
    )
    reference_image_names: StringProperty(
        name="Reference Images",
        description="Comma-separated bpy.data.images names of moodboard stills",
        default="",
    )
    reference_video_names: StringProperty(
        name="Reference Videos",
        description="Comma-separated bpy.data.images names of moodboard movies",
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
            split_names,
        )
        from mixar.modules.moodboard.core.media_utils import describe_moodboard_media
        from mixar.modules.moodboard.core.video_generation_catalog import (
            build_image_reference_inputs,
            build_video_reference_inputs,
            get_video_generation_limits,
            video_reference_count_error,
        )

        clear_agent_gen_reason(context)
        prompt = (self.prompt or "").strip()
        if not prompt:
            return _fail(context, "prompt is required for video generation")

        try:
            model = resolve_agent_model(
                SERVICE_KEY, self.model,
                get_model=get_model, get_default=get_default_model_slug,
            )
        except ValueError as exc:
            return _fail(context, str(exc))

        # Model-aware: H3's reference ceilings are far tighter than Seedance's
        # and everything below this line uploads.
        limits = get_video_generation_limits(SERVICE_KEY, model)
        if limits is None:
            return _fail(context, "Video generation catalog config is incomplete")

        scene = context.scene
        try:
            images = find_moodboard_media(
                scene, split_names(self.reference_image_names),
                describe=describe_moodboard_media, want_video=False,
            )
            videos = find_moodboard_media(
                scene, split_names(self.reference_video_names),
                describe=describe_moodboard_media, want_video=True,
            )
            params = merge_catalog_params(get_model(SERVICE_KEY, model), self.params)
        except ValueError as exc:
            return _fail(context, str(exc))

        count_error = video_reference_count_error(
            limits,
            image_count=len(images),
            video_count=len(videos),
            image_mode=params.get("image_mode"),
        )
        if count_error:
            return _fail(context, count_error)

        try:
            video_inputs = build_video_reference_inputs(videos, limits)
        except ValueError as exc:
            return _fail(context, str(exc))

        image_inputs = []
        try:
            from mixar.modules.common.utils.image_utils import compress_for_service

            image_inputs = build_image_reference_inputs(
                images, limits, compress_for_service
            )
        except ValueError as exc:
            return _fail(context, str(exc))
        except Exception as exc:
            logger.exception("Could not prepare agent video image references")
            return _fail(context, f"Could not prepare image references: {exc}")

        try:
            from mixar.modules.common.job_queue import enqueue_generation
            from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_GEN

            job = enqueue_generation(
                kind="video",
                feature_key=FEATURE_VIDEO_GEN,
                job_type=SERVICE_KEY,
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
            )
        except Exception as exc:
            logger.exception("Could not start agent video generation")
            return _fail(context, f"Failed to start video generation: {exc}")
        if job is None:
            return _fail(context, "A duplicate video generation is already queued")

        try:
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
                mark_enqueued,
            )

            mark_enqueued(FEATURE_VIDEO_GEN)
        except Exception:
            pass

        self.report({'INFO'}, "Video generation started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_video_generate,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
