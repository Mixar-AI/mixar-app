# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Rig Generate Operator (catalog-driven tab).

Resolves the Auto Rig tab's catalog service/model and fans out one Tripo
auto-rig job per selected mesh (GLB export, size cap, import hook stamps
the rig job id on every imported object).
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_animate_generate(Operator):
    """Auto-rig the selected meshes"""

    bl_idname = "mixie.animate_generate"
    bl_label = "Auto Rig"
    bl_description = "Auto-rig the selected meshes (one job per mesh)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params, resolve_model_slug, resolve_service_key,
        )
        from mixar.modules.hunyuan.constants import (
            ANIMATE_RIG_MODEL,
            ANIMATE_RIG_SERVICE,
        )
        from mixar.modules.hunyuan.core.animate_enqueue import enqueue_rig_jobs

        scene = context.scene
        sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
        tab = getattr(sidebar, "tab_animate", None) if sidebar else None
        if tab is None:
            self.report({"WARNING"}, "Auto Rig tab not available")
            return {"CANCELLED"}

        selected_meshes = [
            o for o in context.selected_objects if o.type == 'MESH'
        ]
        if not selected_meshes:
            self.report({"WARNING"}, "No mesh selected")
            return {"CANCELLED"}

        service_key = resolve_service_key(
            "animate", getattr(tab, "mode", "")
        ) or ANIMATE_RIG_SERVICE
        model = resolve_model_slug(
            service_key, getattr(tab, "model", ""), ANIMATE_RIG_MODEL,
        )

        params = {}
        try:
            params = collect_params(service_key, model)
        except Exception as e:
            logger.debug("collect_params failed for %s/%s: %s",
                         service_key, model, e)

        try:
            enqueued = enqueue_rig_jobs(
                context=context,
                objects=selected_meshes,
                service_key=service_key,
                model=model,
                params=params,
                operator=self,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start Auto Rig: {e}")
            return {"CANCELLED"}
        if not enqueued:
            self.report(
                {"WARNING"},
                "No objects could be enqueued (all skipped or failed export)",
            )
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(FEATURE_ANIMATE)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_animate_generate,
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
