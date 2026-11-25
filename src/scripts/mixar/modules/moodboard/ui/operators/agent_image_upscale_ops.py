# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Image Upscale Operator.

Agent-driven entry point for Topaz Image Upscale. Takes ONE explicit
``image_name`` (a moodboard still by datablock name), an optional ``model``
slug and the model's catalog ``params`` as one JSON string, and dispatches
through the SAME ``prepare_image_upscale_source`` / ``enqueue_image_upscale``
path the canvas node uses — so the source checks, the upload ``purpose`` and
the single ``image_s3_key`` payload shape are shared.

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


class MIXIE_OT_agent_image_upscale(Operator):
    """Upscale one named moodboard image with Topaz (agent entry)"""

    bl_idname = "mixie.agent_image_upscale"
    bl_label = "Agent Image Upscale"
    bl_description = "Upscale the named moodboard image with Topaz"
    bl_options = {'REGISTER'}

    image_name: StringProperty(
        name="Image",
        description="bpy.data.images name of the moodboard still to upscale",
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
        from mixar.modules.moodboard.core.image_upscale_catalog import SERVICE_KEY
        from mixar.modules.moodboard.core.image_upscale_enqueue import (
            enqueue_image_upscale,
            prepare_image_upscale_source,
        )
        from mixar.modules.moodboard.core.media_utils import describe_moodboard_media

        clear_agent_gen_reason(context)
        name = (self.image_name or "").strip()
        if not name:
            return _fail(context, "image_name is required for image upscale")

        try:
            model = resolve_agent_model(
                SERVICE_KEY, self.model,
                get_model=get_model, get_default=get_default_model_slug,
            )
            (media,) = find_moodboard_media(
                context.scene, [name],
                describe=describe_moodboard_media, want_video=False,
            )
            params = merge_catalog_params(get_model(SERVICE_KEY, model), self.params)
            # The same checks the node runs (size, output cap) before upload.
            source_input, limits = prepare_image_upscale_source(media["image"], params)
        except ValueError as exc:
            return _fail(context, str(exc))

        try:
            job = enqueue_image_upscale(
                service_key=SERVICE_KEY,
                model=model,
                params=params,
                source_input=source_input,
                limits=limits,
                source_name=name,
            )
        except Exception as exc:
            logger.exception("Could not start agent image upscale")
            return _fail(context, f"Failed to start image upscale: {exc}")
        if job is None:
            return _fail(context, "A duplicate image upscale is already queued")

        try:
            from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_UPSCALE
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
                mark_enqueued,
            )

            mark_enqueued(FEATURE_IMAGE_UPSCALE)
        except Exception:
            pass

        self.report({'INFO'}, "Image upscale started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_image_upscale,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
