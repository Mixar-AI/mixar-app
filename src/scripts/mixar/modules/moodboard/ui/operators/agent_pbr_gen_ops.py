# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent PBR Generation Operator.

Agent-driven entry point for Tripo PBR texture generation. Unlike the
interactive ``mixie.pbr_gen_generate`` (which reads the sidebar tab +
viewport selection), this takes an explicit ``object_name`` plus optional
``prompt`` / ``reference_image_name`` / ``model`` and dispatches ONE
``tripo_texture`` job through the SAME ``enqueue_pbr_texture_job`` helper the
UI uses — so export / size-cap / queue / import are all shared.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason and
return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_PBR_GEN_SERVICE = "tripo_texture"
_PBR_GEN_MODEL_FALLBACK = "tripo_texture_v3"


def _fail(context, reason: str):
    """Record the reason for the agent and cancel."""
    try:
        context.window_manager['mixar_agent_gen_reason'] = reason
    except Exception:
        pass
    return {'CANCELLED'}


class MIXIE_OT_agent_pbr_generate(Operator):
    """Generate PBR textures for a named mesh object via Tripo (agent entry)"""

    bl_idname = "mixie.agent_pbr_generate"
    bl_label = "Agent PBR Generation"
    bl_description = "Generate PBR textures for the given mesh object using Tripo"
    bl_options = {'REGISTER'}

    object_name: StringProperty(
        name="Object Name",
        description="Name of the mesh object in the scene to texture",
        default="",
    )
    prompt: StringProperty(
        name="Prompt",
        description="Optional text guidance for the textures",
        default="",
    )
    reference_image_name: StringProperty(
        name="Reference Image",
        description="Optional bpy.data.images name guiding the textures",
        default="",
    )
    model: StringProperty(
        name="Model Slug",
        description="Model slug from the catalog (empty = catalog default)",
        default="",
    )

    def execute(self, context):
        from mixar.modules.common.generation_params import resolve_model_slug
        from mixar.modules.moodboard.core.pbr_gen_enqueue import (
            enqueue_pbr_texture_job,
        )

        name = (self.object_name or "").strip()
        if not name:
            return _fail(context, "object_name is required for PBR generation")

        obj = bpy.data.objects.get(name)
        if obj is None:
            return _fail(context, f"No object named '{name}' in the scene")
        if obj.type != 'MESH':
            return _fail(
                context,
                f"'{name}' is a {obj.type} object, not a mesh — PBR "
                "generation needs a mesh.",
            )

        reference_image = None
        ref_name = (self.reference_image_name or "").strip()
        if ref_name:
            reference_image = bpy.data.images.get(ref_name)
            if reference_image is None:
                return _fail(
                    context,
                    f"No image named '{ref_name}' in bpy.data.images",
                )

        prompt = (self.prompt or "").strip()
        if not prompt and reference_image is None:
            return _fail(
                context,
                "Provide a prompt or a reference_image_name for PBR "
                "generation.",
            )

        model = (self.model or "").strip()
        if not model:
            try:
                model = resolve_model_slug(
                    _PBR_GEN_SERVICE, "", _PBR_GEN_MODEL_FALLBACK)
            except Exception:
                model = _PBR_GEN_MODEL_FALLBACK

        job = enqueue_pbr_texture_job(
            context,
            objects=[obj],
            service_key=_PBR_GEN_SERVICE,
            model=model,
            prompt=prompt,
            reference_image=reference_image,
            label=name,
            operator=self,
        )
        if job is None:
            # The helper already set mixar_agent_gen_reason; keep it.
            reason = context.window_manager.get('mixar_agent_gen_reason', '')
            return _fail(
                context,
                reason or f"Could not queue PBR generation for '{name}'.",
            )

        try:
            from mixar.modules.common.job_queue.constants import FEATURE_PBR_GEN
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
                mark_enqueued,
            )
            mark_enqueued(FEATURE_PBR_GEN)
        except Exception:
            pass

        self.report({'INFO'}, "PBR generation started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_pbr_generate,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
