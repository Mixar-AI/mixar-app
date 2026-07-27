# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Segmentation Generate Operators (catalog-driven tabs).

Interactive counterparts to the agent operators in ``agent_segment_ops``:
these read the sidebar tab + selection instead of taking explicit params, then
hand off to the same enqueue helpers, so payload assembly, export, size limits
and the import hook (parts collection, part naming, source hidden) are shared.

* ``mixie.tripo_segment_generate`` — Mesh Segmentation tab, one job per
  selected mesh (``/v3/mesh/segment``).
* ``mixie.smart_segment_generate`` — Model Gen tab, one job for the selected
  moodboard image (``/v3/mesh/smartsegment``, which models AND segments).
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_tripo_segment_generate(Operator):
    """Split the selected meshes into parts using Tripo"""

    bl_idname = "mixie.tripo_segment_generate"
    bl_label = "Segment Mesh"
    bl_description = "Split the selected meshes into parts (one job per mesh)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params, resolve_model_slug, resolve_service_key,
        )
        from mixar.modules.hunyuan.constants import (
            SEGMENT_MODEL, SEGMENT_SERVICE,
        )
        from mixar.modules.hunyuan.core.segment_enqueue import (
            enqueue_segment_jobs,
        )

        scene = context.scene
        sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
        tab = getattr(sidebar, 'tab_mesh_segment', None) if sidebar else None
        if tab is None:
            self.report({"WARNING"}, "Mesh Segment tab not available")
            return {"CANCELLED"}

        selected_meshes = [
            o for o in context.selected_objects if o.type == 'MESH'
        ]
        if not selected_meshes:
            self.report({"WARNING"}, "No mesh selected")
            return {"CANCELLED"}

        service_key = resolve_service_key(
            "mesh_segmentation", getattr(tab, "mode", "")
        ) or SEGMENT_SERVICE
        model = resolve_model_slug(
            service_key, getattr(tab, 'model', ''), SEGMENT_MODEL,
        )
        params = collect_params(service_key, model)

        # ref_image is a client-side pointer, not a catalog param. Tripo
        # ignores granularity / connectivity when a mask is supplied, so drop
        # them rather than send params the vendor will discard.
        ref_image = getattr(tab, 'ref_image', None)
        if ref_image is not None:
            params.pop("segmentation_granularity", None)
            params.pop("split_by_connectivity", None)

        try:
            enqueued = enqueue_segment_jobs(
                context=context,
                objects=selected_meshes,
                service_key=service_key,
                model=model,
                params=params,
                ref_image=ref_image,
                operator=self,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[Segment] enqueue failed: %s", e)
            self.report({"ERROR"}, f"Segmentation failed: {e}")
            return {"CANCELLED"}

        if not enqueued:
            self.report({"WARNING"}, "No segmentation jobs were queued")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Segmenting {len(enqueued)} mesh(es)...")
        return {"FINISHED"}


class MIXIE_OT_smart_segment_generate(Operator):
    """Generate a segmented 3D model from the selected image using Tripo"""

    bl_idname = "mixie.smart_segment_generate"
    bl_label = "Generate Parts"
    bl_description = (
        "Generate a 3D model from the selected image and split it into parts"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            collect_params, resolve_model_slug, resolve_service_key,
        )
        from mixar.modules.hunyuan.constants import (
            SMART_SEGMENT_MODEL, SMART_SEGMENT_SERVICE,
        )
        from mixar.modules.hunyuan.core.segment_enqueue import (
            enqueue_smart_segment_job,
        )
        from ..sidebar_ui_helpers import get_selected_moodboard_image

        image = get_selected_moodboard_image(context)
        if image is None:
            self.report({"WARNING"}, "No moodboard image selected")
            return {"CANCELLED"}

        service_key = resolve_service_key(
            "model_gen", getattr(
                getattr(getattr(context.scene, 'mixie_moodboard_sidebar', None),
                        'tab_image_to_3d', None),
                "mode", "",
            ),
        ) or SMART_SEGMENT_SERVICE
        model = resolve_model_slug(service_key, "", SMART_SEGMENT_MODEL)
        params = collect_params(service_key, model)

        try:
            job = enqueue_smart_segment_job(
                image=image,
                service_key=service_key,
                model=model,
                params=params,
                operator=self,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[SmartSegment] enqueue failed: %s", e)
            self.report({"ERROR"}, f"Smart segmentation failed: {e}")
            return {"CANCELLED"}

        if job is None:
            self.report({"WARNING"}, "Smart segmentation was not queued")
            return {"CANCELLED"}

        self.report({"INFO"}, "Generating segmented model...")
        return {"FINISHED"}


classes = (MIXIE_OT_tripo_segment_generate, MIXIE_OT_smart_segment_generate)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
