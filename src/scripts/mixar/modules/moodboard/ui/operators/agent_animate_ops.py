# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Animate operator — preset animations onto an Auto Rig result.

``mixie.agent_animate`` is a frozen agent contract (``bl_idname`` and props):
``object_name`` names the rigged armature or any mesh it drives,
``animations`` is a comma-separated list of catalog preset values
(``preset:biped:walk``), ``animate_in_place`` the in-place toggle. The rig
job is resolved with ``find_rig_job_id`` from the ``mixar_rig_job_id`` stamp
an Auto Rig import carries, the job goes on the shared Animate queue, and the
result's clips are merged onto that character — so the job reports the
ORIGINAL character's object names (armature + meshes) as its result names.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set ``window_manager['mixar_agent_gen_reason']``
to a human-readable reason and return ``{'CANCELLED'}``.
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

logger = get_logger(__name__)


def _fail(context, reason: str):
    set_agent_gen_reason(context, reason)
    return {'CANCELLED'}


def plan_agent_animate(obj, animations: str, animate_in_place: bool) -> tuple:
    """``(submission, reason)``: everything the enqueue needs, or why not.

    Pure resolution so it is testable without an Operator: the rig stamp,
    the live retarget catalog, the preset list and the skeleton rule.
    """
    from mixar.modules.hunyuan.constants import ANIMATE_IN_PLACE_PARAM, ANIMATE_PRESETS_PARAM
    from mixar.modules.hunyuan.core.animate_enqueue import find_rig_job_id, find_rig_skeleton
    from mixar.modules.hunyuan.core.animate_presets import (
        parse_preset_list,
        preset_error,
        retarget_catalog,
    )

    rig_job_id = find_rig_job_id(obj)
    if not rig_job_id:
        return None, (
            f"'{obj.name}' was not imported by Auto Rig — run mixie.agent_auto_rig on the "
            "character first, then animate the rigged result."
        )
    service_key, model, choices = retarget_catalog()
    if not service_key or not model:
        return None, "Animate is unavailable in the generation catalog"
    presets = parse_preset_list(animations)
    error = preset_error(presets, choices, find_rig_skeleton(obj))
    if error:
        return None, error
    armature = obj if obj.type == 'ARMATURE' else (obj.find_armature() or obj)
    return {
        "rig_job_id": rig_job_id,
        "service_key": service_key,
        "model": model,
        "params": {
            ANIMATE_PRESETS_PARAM: presets,
            ANIMATE_IN_PLACE_PARAM: bool(animate_in_place),
        },
        "label": armature.name,
        "rig_name": armature.name,
    }, ""


class MIXIE_OT_agent_animate(Operator):
    """Apply preset animations to an auto-rigged character (agent entry point)"""

    bl_idname = "mixie.agent_animate"
    bl_label = "Agent Animate"
    bl_description = "Retarget preset animations onto an Auto Rig result"
    bl_options = {'REGISTER'}

    object_name: StringProperty(
        name="Object Name",
        description="The rigged armature, or any mesh it drives, imported by Auto Rig",
        default="",
    )
    animations: StringProperty(
        name="Animations",
        description="Comma-separated preset values from the animation catalog, "
                    "e.g. 'preset:biped:walk,preset:biped:idle' (1-10, the rig's skeleton)",
        default="",
    )
    animate_in_place: BoolProperty(
        name="In Place",
        description="Keep the character on the spot instead of travelling with the clip",
        default=False,
    )

    def execute(self, context):
        from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
        from mixar.modules.hunyuan.core.animate_enqueue import enqueue_retarget_job

        name = (self.object_name or "").strip()
        if not name:
            return _fail(context, "object_name is required for animate")
        obj = bpy.data.objects.get(name)
        if obj is None:
            return _fail(context, f"No object named '{name}' in the scene.")

        submission, reason = plan_agent_animate(obj, self.animations, self.animate_in_place)
        if submission is None:
            return _fail(context, reason)
        try:
            job = enqueue_retarget_job(**submission)
        except Exception as e:
            logger.warning("[AgentAnimate] enqueue failed: %s", e)
            return _fail(context, f"Animate submission failed: {e}")
        if job is None:
            return _fail(
                context,
                f"An animate job for '{submission['label']}' with these presets is "
                "already queued or running — wait for it to finish.",
            )
        try:
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued

            mark_enqueued(FEATURE_ANIMATE)
        except Exception:
            pass
        self.report({'INFO'}, "Animate started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_animate,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
