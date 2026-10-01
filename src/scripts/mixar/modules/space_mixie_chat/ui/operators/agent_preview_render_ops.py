# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sandbox-facing entry point of the agent's asynchronous preview render.

The backend's ``render_viewport(quality="final")`` script calls
``bpy.ops.mixie_chat.agent_preview_render(job_key=<32 hex>, width=, height=,
engine=, max_faces=<int>)`` and reads ONE plain dict from
``bpy.app.driver_namespace['mixie_agent_preview_response']``
(``running`` | ``busy`` | ``failed``; see ``core/preview_render.py`` for the
keys). On ``running`` the script returns ``{"__deferred_preview__": key}`` and
the executor holds the tool call open until the job ends
(``core/preview_deferral.py``). Polling stays internal to the client.
"""

import bpy

from ...core import preview_render

RESPONSE_NS = "mixie_agent_preview_response"


class MIXIE_CHAT_OT_agent_preview_render(bpy.types.Operator):
    """Start the agent's bounded preview render as a native background job"""

    bl_idname = "mixie_chat.agent_preview_render"
    bl_label = "Agent Preview Render"
    bl_options = {"INTERNAL"}

    job_key: bpy.props.StringProperty()
    # The render's real size (0 = keep the scene's, scaled to the preview cap)
    # and engine ("eevee" | "cycles"; "" = keep the scene's own).
    width: bpy.props.IntProperty(default=0, min=0, max=8192)
    height: bpy.props.IntProperty(default=0, min=0, max=8192)
    engine: bpy.props.StringProperty(default="")
    # The backend's machine-derived geometry budget. A render whose CHOSEN engine
    # is Cycles on a scene above it is downgraded to EEVEE rather than risking the
    # OS killing the app (docs/render-job-contract.md). 0 = no limit, which is what
    # an older backend that does not send the parameter gets.
    max_faces: bpy.props.IntProperty(default=0, min=0)

    def execute(self, context):
        # A single response slot; retained job results live in the core module.
        bpy.app.driver_namespace[RESPONSE_NS] = preview_render.start(
            context, self.job_key, width=self.width, height=self.height,
            engine=self.engine, max_faces=self.max_faces)
        return {"FINISHED"}


classes = (MIXIE_CHAT_OT_agent_preview_render,)
