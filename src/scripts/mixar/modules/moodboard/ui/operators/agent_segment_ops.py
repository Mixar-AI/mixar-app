# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Segmentation Operators.

Agent-driven entry points for the two Tripo segmentation services. Like
``mixie.agent_auto_rig``, these take explicit params instead of reading the
sidebar tab + viewport selection, and dispatch through the same enqueue
helpers the UI uses — so export / size cap / queue / import (parts collection,
part naming, source hidden) are all shared.

* ``mixie.agent_segment_mesh``  — split a mesh already in the scene.
* ``mixie.agent_smart_segment`` — image → auto-modelled, segmented parts.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason and
return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# mesh/segment v2 vocabulary. smartsegment uses a DIFFERENT one on purpose —
# keeping them apart here is what stops a coarse/balanced mix-up reaching the
# wire, where Tripo would reject or silently ignore it.
_SEGMENT_GRANULARITIES = {"simple", "balanced", "detailed"}
_SMART_GRANULARITIES = {"coarse", "medium", "fine"}


def _fail(context, reason: str):
    """Record the reason for the agent and cancel."""
    try:
        context.window_manager['mixar_agent_gen_reason'] = reason
    except Exception:
        pass
    return {'CANCELLED'}


def _resolve_model(service_key: str, fallback: str, requested: str = "") -> str:
    """Catalog model slug for the service, falling back to the constant."""
    if requested:
        return requested
    try:
        from mixar.modules.common.generation_params import resolve_model_slug
        return resolve_model_slug(service_key, "", fallback)
    except Exception:
        return fallback


def _duplicate_queued(feature_key: str, label: str) -> bool:
    """True when a live job with this label is already queued for the feature.

    Distinguishes the queue's duplicate-label rejection from a real export
    failure — a wrong "export failed / too large" reason sends the agent down
    pointless corrective paths.
    """
    try:
        from mixar.modules.common.job_queue.core.queue_manager import (
            TERMINAL_STATES, get_queue,
        )
        return any(
            j.label == label and j.state not in TERMINAL_STATES
            for j in get_queue(feature_key)._jobs
        )
    except Exception:
        return False


def _flash_queue(feature_key: str) -> None:
    try:
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(feature_key)
    except Exception:
        pass


class MIXIE_OT_agent_segment_mesh(Operator):
    """Split a named mesh object into parts via Tripo (agent entry point)"""

    bl_idname = "mixie.agent_segment_mesh"
    bl_label = "Agent Segment Mesh"
    bl_description = "Split the given mesh object into parts using Tripo"
    bl_options = {'REGISTER'}

    object_name: StringProperty(
        name="Object Name",
        description="Name of the mesh object in the scene to segment",
        default="",
    )
    model: StringProperty(
        name="Model",
        description="Catalog model slug; empty uses the catalog default",
        default="",
    )
    segmentation_granularity: StringProperty(
        name="Granularity",
        description="Segmentation granularity: simple / balanced / detailed",
        default="balanced",
    )
    split_by_connectivity: BoolProperty(
        name="Split by Connectivity",
        description="Split the result by connected components",
        default=True,
    )
    ref_image_name: StringProperty(
        name="Reference Mask",
        description="Optional bpy.data.images name holding a colour-coded "
                    "segmentation mask that drives the split",
        default="",
    )

    def execute(self, context):
        from mixar.modules.common.job_queue.constants import FEATURE_TRIPO_SEGMENT
        from mixar.modules.hunyuan.constants import (
            SEGMENT_MODEL, SEGMENT_SERVICE,
        )
        from mixar.modules.hunyuan.core.segment_enqueue import (
            enqueue_segment_jobs,
        )

        name = (self.object_name or "").strip()
        if not name:
            return _fail(context, "object_name is required for segmentation")

        obj = bpy.data.objects.get(name)
        if obj is None:
            return _fail(context, f"No object named '{name}' in the scene")
        if obj.type != 'MESH':
            return _fail(
                context,
                f"'{name}' is a {obj.type} object, not a mesh — segmentation "
                "needs a mesh.",
            )

        granularity = (self.segmentation_granularity or "balanced").strip().lower()
        if granularity not in _SEGMENT_GRANULARITIES:
            return _fail(
                context,
                f"Invalid segmentation_granularity "
                f"'{self.segmentation_granularity}'. Expected one of: "
                f"{', '.join(sorted(_SEGMENT_GRANULARITIES))}. (coarse/medium/"
                "fine belong to tripo_smart_segment, not this job.)",
            )

        ref_image = None
        ref_name = (self.ref_image_name or "").strip()
        if ref_name:
            ref_image = bpy.data.images.get(ref_name)
            if ref_image is None:
                return _fail(
                    context,
                    f"No image named '{ref_name}' — ref_image_name must be a "
                    "bpy.data.images name holding a segmentation mask.",
                )

        params = {
            "segmentation_granularity": granularity,
            "split_by_connectivity": bool(self.split_by_connectivity),
        }
        model = _resolve_model(SEGMENT_SERVICE, SEGMENT_MODEL, self.model.strip())

        try:
            enqueued = enqueue_segment_jobs(
                context=context,
                objects=[obj],
                service_key=SEGMENT_SERVICE,
                model=model,
                params=params,
                ref_image=ref_image,
                operator=self,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[AgentSegment] enqueue failed: %s", e)
            return _fail(context, f"Segmentation submission failed: {e}")

        if not enqueued:
            if _duplicate_queued(FEATURE_TRIPO_SEGMENT, name):
                return _fail(
                    context,
                    f"A segmentation job for '{name}' is already queued or "
                    "running — wait for it to finish.",
                )
            return _fail(
                context,
                f"Could not queue segmentation for '{name}' (export failed or "
                "the mesh exceeds the 150 MB limit).",
            )

        _flash_queue(FEATURE_TRIPO_SEGMENT)
        self.report({'INFO'}, "Mesh segmentation started...")
        return {'FINISHED'}


class MIXIE_OT_agent_smart_segment(Operator):
    """Turn an image into a segmented 3D model via Tripo (agent entry point)"""

    bl_idname = "mixie.agent_smart_segment"
    bl_label = "Agent Smart Segment"
    bl_description = (
        "Generate a 3D model from the given image and split it into parts"
    )
    bl_options = {'REGISTER'}

    image_name: StringProperty(
        name="Image Name",
        description="Name of the moodboard / bpy.data image to segment",
        default="",
    )
    model: StringProperty(
        name="Model",
        description="Catalog model slug; empty uses the catalog default",
        default="",
    )
    granularity: StringProperty(
        name="Granularity",
        description="Segmentation granularity: coarse / medium / fine",
        default="medium",
    )
    hint: StringProperty(
        name="Hint",
        description="Free text naming the parts to look for",
        default="",
    )

    def execute(self, context):
        from mixar.modules.common.job_queue.constants import FEATURE_SMART_SEGMENT
        from mixar.modules.hunyuan.constants import (
            SMART_SEGMENT_MODEL, SMART_SEGMENT_SERVICE,
        )
        from mixar.modules.hunyuan.core.segment_enqueue import (
            enqueue_smart_segment_job,
        )

        name = (self.image_name or "").strip()
        if not name:
            return _fail(context, "image_name is required for smart segmentation")

        image = bpy.data.images.get(name)
        if image is None:
            return _fail(
                context,
                f"No image named '{name}' — image_name must be a moodboard / "
                "bpy.data.images name.",
            )

        granularity = (self.granularity or "medium").strip().lower()
        if granularity not in _SMART_GRANULARITIES:
            return _fail(
                context,
                f"Invalid granularity '{self.granularity}'. Expected one of: "
                f"{', '.join(sorted(_SMART_GRANULARITIES))}. (simple/balanced/"
                "detailed belong to tripo_segment, not this job.)",
            )

        params = {"granularity": granularity}
        hint = (self.hint or "").strip()
        if hint:
            params["hint"] = hint

        model = _resolve_model(
            SMART_SEGMENT_SERVICE, SMART_SEGMENT_MODEL, self.model.strip()
        )

        try:
            job = enqueue_smart_segment_job(
                image=image,
                service_key=SMART_SEGMENT_SERVICE,
                model=model,
                params=params,
                operator=self,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[AgentSmartSegment] enqueue failed: %s", e)
            return _fail(context, f"Smart segmentation submission failed: {e}")

        if job is None:
            if _duplicate_queued(FEATURE_SMART_SEGMENT, name):
                return _fail(
                    context,
                    f"A smart segmentation job for '{name}' is already queued "
                    "or running — wait for it to finish.",
                )
            return _fail(
                context,
                f"Could not queue smart segmentation for '{name}' (the image "
                "could not be read).",
            )

        _flash_queue(FEATURE_SMART_SEGMENT)
        self.report({'INFO'}, "Smart segmentation started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_segment_mesh, MIXIE_OT_agent_smart_segment)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
