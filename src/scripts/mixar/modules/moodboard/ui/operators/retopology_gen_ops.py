# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retopology Generate Operator (catalog-driven tab).

Resolves the Retopology tab's catalog service and model — on merged
catalogs one ``retopology`` service carries both engines as models
(``hunyuan_topology`` / ``tripo_v2``); pre-merge catalogs still expose
Tripo as the separate ``retopology_tripo`` service — collects the
model's schema params, and fans out one job per selected mesh through
the EXISTING ``enqueue_retopology_jobs`` helper, so payload assembly
(shared retopology assemblers), per-object export, size limits, and the
import hooks stay identical to the legacy ``mixie.hunyuan_generate``
TOPOLOGY path.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_TRIPO_SERVICE = "retopology_tripo"


class MIXIE_OT_retopology_generate(Operator):
    """Retopologize the selected meshes using the selected mode"""

    bl_idname = "mixie.retopology_generate"
    bl_label = "Retopologize"
    bl_description = "Retopologize the selected meshes (one job per mesh)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params, resolve_model_slug, resolve_service_key,
        )
        from mixar.modules.hunyuan.constants import (
            RETOPOLOGY_HUNYUAN_MODEL,
            RETOPOLOGY_HUNYUAN_SERVICE,
            RETOPOLOGY_TRIPO_MODEL,
        )
        from mixar.modules.hunyuan.core.retopology_enqueue import (
            enqueue_retopology_jobs,
        )

        scene = context.scene
        sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
        tab = getattr(sidebar, 'tab_retopology', None) if sidebar else None
        if tab is None:
            self.report({"WARNING"}, "Retopology tab not available")
            return {"CANCELLED"}

        selected_meshes = [
            o for o in context.selected_objects if o.type == 'MESH'
        ]
        if not selected_meshes:
            self.report({"WARNING"}, "No mesh selected")
            return {"CANCELLED"}

        # --- Resolve mode (service) and model slug from the catalog ---
        service_key = resolve_service_key(
            "retopology", getattr(tab, "mode", "")
        ) or RETOPOLOGY_HUNYUAN_SERVICE
        model = resolve_model_slug(
            service_key,
            getattr(tab, 'model', ''),
            RETOPOLOGY_TRIPO_MODEL if service_key == _TRIPO_SERVICE
            else RETOPOLOGY_HUNYUAN_MODEL,
        )
        # The engine is the model choice on merged catalogs; the dedicated
        # retopology_tripo service only exists pre-merge.
        is_tripo = (
            model == RETOPOLOGY_TRIPO_MODEL or service_key == _TRIPO_SERVICE
        )

        params = {}
        try:
            params = collect_params(service_key, model)
        except Exception as e:
            logger.debug("collect_params failed for %s/%s: %s",
                         service_key, model, e)

        # --- Map catalog params onto the shared enqueue snapshot ---
        # service_key rides along so the enqueue submits to whichever
        # service the catalog linked the model under.
        shared = {"model_slug": model, "service_key": service_key}
        if is_tripo:
            topo = scene.hunyuan.topology if hasattr(scene, 'hunyuan') else None
            shared["model"] = "tripo"
            shared["tripo_quad"] = bool(params.get("quad", False))
            shared["tripo_face_limit"] = params.get("face_limit") or 10000
            # Client-side flag — not a catalog param.
            shared["tripo_bake"] = (
                bool(getattr(topo, "tripo_bake", True)) if topo else True
            )
        else:
            shared["model"] = "hunyuan"
            shared["polygon_type"] = params.get("polygon_type")
            shared["face_level"] = params.get("face_level")
            shared["post_process"] = bool(params.get("post_process", True))

        try:
            enqueued = enqueue_retopology_jobs(
                context=context,
                objects=selected_meshes,
                shared=shared,
                operator=self,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start retopology: {e}")
            return {"CANCELLED"}
        if not enqueued:
            self.report(
                {"WARNING"},
                "No objects could be enqueued (all skipped or failed export)",
            )
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(FEATURE_RETOPOLOGY)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_retopology_generate,
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
