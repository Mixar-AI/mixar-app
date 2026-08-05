# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Auto Rig Operator.

Agent-driven entry point for Tripo auto-rigging. Unlike the interactive
``mixie.animate_generate`` (which reads the sidebar tab + viewport
selection), this operator takes an explicit ``object_name`` plus rig
params and dispatches ONE ``tripo_rig`` job through the same
``enqueue_rig_jobs`` helper the UI uses — so export / size-cap / queue /
import (with ``guess_original_bind_pose=False``) are all shared.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason
and return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_RIG_TYPES = {
    "auto", "biped", "quadruped", "hexapod", "octopod",
    "avian", "serpentine", "aquatic",
}
_SPECS = {"tripo", "mixamo"}


def _fail(context, reason: str):
    """Record the reason for the agent and cancel."""
    try:
        context.window_manager['mixar_agent_gen_reason'] = reason
    except Exception:
        pass
    return {'CANCELLED'}


class MIXIE_OT_agent_auto_rig(Operator):
    """Auto-rig a named mesh object via Tripo (agent entry point)"""

    bl_idname = "mixie.agent_auto_rig"
    bl_label = "Agent Auto Rig"
    bl_description = "Auto-rig the given mesh object using Tripo"
    bl_options = {'REGISTER'}

    object_name: StringProperty(
        name="Object Name(s)",
        description="Name of the mesh object to auto-rig. To rig a segmented "
                    "character, pass ALL its part names comma-separated — they "
                    "are combined into ONE skeleton (e.g. 'Head,Torso,Arm_L').",
        default="",
    )
    rig_type: StringProperty(
        name="Rig Type",
        description="Skeleton type: auto / biped / quadruped / hexapod / "
                    "octopod / avian / serpentine / aquatic",
        default="auto",
    )
    spec: StringProperty(
        name="Skeleton Spec",
        description="Skeleton convention: 'tripo' or 'mixamo'",
        default="tripo",
    )

    def execute(self, context):
        from mixar.modules.hunyuan.constants import (
            ANIMATE_RIG_MODEL, ANIMATE_RIG_SERVICE, MAX_FILE_SIZE_ANIMATE_RIG,
        )
        from mixar.modules.hunyuan.core.animate_enqueue import (
            enqueue_rig_jobs, _rig_label,
        )

        raw = (self.object_name or "").strip()
        if not raw:
            return _fail(context, "object_name is required for auto-rig")

        # One name or several comma-separated (a segmented character). Resolve
        # each; every part must exist and be a mesh — they are exported together
        # into ONE GLB and rigged as a single skeleton by enqueue_rig_jobs.
        names, seen = [], set()
        for part in raw.split(","):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                names.append(part)

        meshes, missing, non_mesh = [], [], []
        for nm in names:
            obj = bpy.data.objects.get(nm)
            if obj is None:
                missing.append(nm)
            elif obj.type != 'MESH':
                non_mesh.append(f"'{nm}' ({obj.type})")
            else:
                meshes.append(obj)

        if missing:
            return _fail(
                context,
                f"No object(s) named {', '.join(repr(m) for m in missing)} "
                "in the scene.",
            )
        if non_mesh:
            return _fail(
                context,
                f"Not a mesh: {', '.join(non_mesh)} — auto-rig needs mesh "
                "objects.",
            )
        if not meshes:
            return _fail(context, "No mesh objects to auto-rig")

        rig_type = (self.rig_type or "auto").strip().lower()
        if rig_type not in _RIG_TYPES:
            return _fail(
                context,
                f"Invalid rig_type '{self.rig_type}'. Expected one of: "
                f"{', '.join(sorted(_RIG_TYPES))}.",
            )
        skel = (self.spec or "tripo").strip().lower()
        if skel not in _SPECS:
            return _fail(
                context,
                f"Invalid spec '{self.spec}'. Expected 'tripo' or 'mixamo'.",
            )

        # Resolve the catalog model slug (falls back to the constant when the
        # catalog isn't loaded); enqueue_rig_jobs sends it as the model slug
        # and the backend routes by its model_ref.
        model = ANIMATE_RIG_MODEL
        try:
            from mixar.modules.common.generation_params import resolve_model_slug
            model = resolve_model_slug(
                ANIMATE_RIG_SERVICE, "", ANIMATE_RIG_MODEL,
            )
        except Exception:
            pass

        params = {"rig_type": rig_type, "spec": skel}
        try:
            enqueued = enqueue_rig_jobs(
                context=context,
                objects=meshes,
                service_key=ANIMATE_RIG_SERVICE,
                model=model,
                params=params,
                operator=self,
            )
        except Exception as e:
            logger.warning("[AgentAutoRig] enqueue failed: %s", e)
            return _fail(context, f"Auto-rig submission failed: {e}")

        target = ", ".join(m.name for m in meshes)
        if not enqueued:
            # Distinguish the queue's duplicate-label rejection from a real
            # export/size failure — a wrong "export failed / too large" reason
            # sends the agent down pointless corrective paths (decimation).
            try:
                from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
                from mixar.modules.common.job_queue.core.queue_manager import (
                    TERMINAL_STATES,
                    get_queue,
                )

                expected_label = _rig_label(context, meshes)
                duplicate = any(
                    j.label == expected_label and j.state not in TERMINAL_STATES
                    for j in get_queue(FEATURE_ANIMATE)._jobs
                )
            except Exception:
                duplicate = False
            if duplicate:
                return _fail(
                    context,
                    f"An auto-rig job for '{target}' is already queued or "
                    "running — wait for it to finish.",
                )
            return _fail(
                context,
                f"Could not queue auto-rig for '{target}' (export failed or "
                f"the combined mesh exceeds the "
                f"{MAX_FILE_SIZE_ANIMATE_RIG // (1024 * 1024)} MB limit).",
            )

        # Mirror the interactive operator: flash the Animate/Auto Rig queue.
        try:
            from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
                mark_enqueued,
            )
            mark_enqueued(FEATURE_ANIMATE)
        except Exception:
            pass

        self.report({'INFO'}, "Auto-rig started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_auto_rig,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
