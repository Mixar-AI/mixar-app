# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PBR Generation Operator (catalog-driven tab).

Interactive entry point: textures the selected untextured mesh via Tripo's
texture-model service (``tripo_texture``). Reads the sidebar tab's guidance
(single reference image / four positional views / prompt) and submits one
job through the shared ``enqueue_pbr_texture_job`` helper — the SAME helper
the agent operator (``mixie.agent_pbr_generate``) uses, so export / payload /
queue never diverge.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_PBR_GEN_SERVICE = "tripo_texture"
_PBR_GEN_MODEL_FALLBACK = "tripo_texture_v3"

# Four positional views in the order the backend expects (front/left/back/right).
_VIEW_ORDER = ("front_image", "left_image", "back_image", "right_image")


def _get_tab(context):
    sidebar = getattr(context.scene, "mixie_moodboard_sidebar", None)
    return getattr(sidebar, "tab_pbr_gen", None) if sidebar else None


def _single_reference_image(context, tab):
    """The single-mode reference image (moodboard-selected or manual)."""
    if getattr(tab, "use_selected_image", False):
        scene = context.scene
        if hasattr(scene, "mixie_moodboard_images"):
            for item in scene.mixie_moodboard_images:
                if item.selected and item.image:
                    return item.image
        return None
    return getattr(tab, "reference_image", None)


class MIXIE_OT_pbr_gen_generate(Operator):
    """Texture the selected mesh with Tripo PBR Generation"""

    bl_idname = "mixie.pbr_gen_generate"
    bl_label = "Generate PBR"
    bl_description = "Texture the selected untextured mesh (Tripo)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params, resolve_model_slug, resolve_service_key,
        )
        from mixar.modules.moodboard.core.pbr_gen_enqueue import (
            enqueue_pbr_texture_job,
        )

        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "PBR Generation tab not available")
            return {"CANCELLED"}

        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({"ERROR"}, "No mesh selected")
            return {"CANCELLED"}

        service_key = resolve_service_key(
            "pbr_generation", getattr(tab, "mode", "")) or _PBR_GEN_SERVICE
        model = resolve_model_slug(
            service_key, getattr(tab, "model", ""), _PBR_GEN_MODEL_FALLBACK)

        # Guidance from the tab: four positional views or a single reference.
        view_images = None
        reference_image = None
        style_only = False
        if getattr(tab, "multi_view", False):
            view_images = [getattr(tab, prop, None) for prop in _VIEW_ORDER]
        else:
            reference_image = _single_reference_image(context, tab)
            style_only = bool(getattr(tab, "style_only", False))

        params = {}
        try:
            params = collect_params(service_key, model)
        except Exception as e:
            logger.debug("collect_params failed for %s/%s: %s",
                         service_key, model, e)

        job = enqueue_pbr_texture_job(
            context,
            objects=meshes,
            service_key=service_key,
            model=model,
            prompt=getattr(tab, "prompt", ""),
            reference_image=reference_image,
            style_only=style_only,
            view_images=view_images,
            params=params,
            label=meshes[0].name,
            operator=self,
        )
        if job is None:
            return {"CANCELLED"}  # helper already reported the reason

        from mixar.modules.common.job_queue.constants import FEATURE_PBR_GEN
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(FEATURE_PBR_GEN)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_pbr_gen_generate,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
