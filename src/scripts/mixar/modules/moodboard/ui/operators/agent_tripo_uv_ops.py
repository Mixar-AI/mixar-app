# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Smart UV Operator.

``mixie.agent_tripo_uv`` — the agent's ``tripo_uv`` job type: re-unwrap a
named scene mesh through Tripo Smart UV. Shares the export, limits, queue and
import (``<object>_uv`` result, atlas on the board) with the Moodboard Smart UV
node through ``hunyuan.core.tripo_uv_enqueue``.

Contract with the agent's ``enqueue_generation`` tool: on success return
``{'FINISHED'}``; on any refusal set
``window_manager['mixar_agent_gen_reason']`` to a human-readable reason and
return ``{'CANCELLED'}`` (the agent script reads that prop).
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from .agent_segment_ops import _duplicate_queued, _fail, _flash_queue

logger = get_logger(__name__)


class MIXIE_OT_agent_tripo_uv(Operator):
    """Re-unwrap a named mesh object's UVs via Tripo Smart UV (agent entry point)"""

    bl_idname = "mixie.agent_tripo_uv"
    bl_label = "Agent Smart UV"
    bl_description = "Re-unwrap the given mesh object's UVs using Tripo Smart UV"
    bl_options = {'REGISTER'}

    object_name: StringProperty(
        name="Object Name",
        description="Name of the mesh object in the scene to unwrap",
        default="",
    )
    bake: BoolProperty(
        name="Bake Textures",
        description="Bake the existing textures onto the new UV layout",
        default=True,
    )

    def execute(self, context):
        from mixar.modules.common.job_queue.constants import FEATURE_TRIPO_UV
        from mixar.modules.hunyuan.core.tripo_uv_enqueue import enqueue_tripo_uv_job

        name = (self.object_name or "").strip()
        if not name:
            return _fail(context, "object_name is required for Smart UV")
        obj = bpy.data.objects.get(name)
        if obj is None:
            return _fail(context, f"No object named '{name}' in the scene")
        if obj.type != 'MESH':
            return _fail(
                context,
                f"'{name}' is a {obj.type} object, not a mesh — Smart UV needs a mesh.",
            )

        try:
            job = enqueue_tripo_uv_job(context=context, obj=obj, bake=self.bake)
        except ValueError as e:
            return _fail(context, str(e))
        except Exception as e:  # noqa: BLE001
            logger.warning("[AgentSmartUV] enqueue failed: %s", e)
            return _fail(context, f"Smart UV submission failed: {e}")

        if job is None:
            if _duplicate_queued(FEATURE_TRIPO_UV, name):
                return _fail(
                    context,
                    f"A Smart UV job for '{name}' is already queued or running — "
                    "wait for it to finish.",
                )
            return _fail(context, f"Could not queue Smart UV for '{name}'.")

        _flash_queue(FEATURE_TRIPO_UV)
        self.report({'INFO'}, "Smart UV started...")
        return {'FINISHED'}


classes = (MIXIE_OT_agent_tripo_uv,)
