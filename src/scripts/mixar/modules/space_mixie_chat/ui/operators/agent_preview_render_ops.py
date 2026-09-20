# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sandbox-facing entry point of the agent's asynchronous preview render.

The backend's ``render_viewport(quality="final")`` script calls
``bpy.ops.mixie_chat.agent_preview_render(job_key=<32 hex>)`` and reads ONE
plain dict from ``bpy.app.driver_namespace['mixie_agent_preview_response']``
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

    def execute(self, context):
        # A single response slot; retained job results live in the core module.
        bpy.app.driver_namespace[RESPONSE_NS] = preview_render.start(context, self.job_key)
        return {"FINISHED"}


classes = (MIXIE_CHAT_OT_agent_preview_render,)
