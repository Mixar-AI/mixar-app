# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Quick Prompt Operator for Mixie Chat

Global keyboard shortcut operator for quickly sending messages to Mixie Chat.
Uses WebSocket for chat streaming.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger

from ...constants import DEV_MODE, MAX_MESSAGE_LENGTH, SessionState
from ...core import (
    get_dummy_response,
    get_session_manager,
)
from ...core.composer_send import can_send
from ...core.connection_manager import get_connection_manager
from ...core.jsonrpc_client import get_jsonrpc_client
from ...core.turn_transport import create_turn_handler
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


def _get_auth_token() -> str:
    """Get authentication token."""
    try:
        from mixar.modules.auth.core.auth import get_access_token
        return get_access_token() or ""
    except Exception:
        return ""


class MIXIE_CHAT_OT_quick_prompt(Operator):
    """Open a quick prompt window to send a message to Mixie Chat"""

    bl_idname = "mixie_chat.quick_prompt"
    bl_label = "Send to Mixie Chat"
    bl_description = "Open a prompt to send a message to Mixie Chat (Enter to send)"
    bl_options = {'REGISTER'}

    # Keep operator property for direct invocation, but UI uses window_manager property
    message: StringProperty(
        name="",
        description="Message to send to Mixie Chat",
        default="",
        maxlen=MAX_MESSAGE_LENGTH,
        options={'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        wm = context.window_manager
        scene = context.scene

        # Successful sends clear this property.  Preserve any non-empty draft
        # left by Cancel or Add-on Project folder setup so reopening the quick
        # prompt never destroys unsent work.

        # Initialize quick prompt mode from current footer mode
        wm.mixie_chat_quick_prompt_mode = scene.mixie_chat_mode
        wm.mixie_chat_quick_prompt_generate_type = scene.mixie_chat_generate_type

        # Show popup dialog - wider to accommodate mode controls
        return wm.invoke_props_dialog(self, width=600)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        scene = context.scene

        session = get_session_manager()
        connection_manager = get_connection_manager()

        # Show connection status
        if not DEV_MODE and not connection_manager.is_connected:
            row = layout.row()
            row.alert = True
            row.label(text="Not connected to Mixie Chat", icon='ERROR')
        elif not DEV_MODE and not can_send(scene)[0]:
            row = layout.row()
            row.alert = True
            row.label(text=can_send(scene)[1] or "Mixie Chat is busy", icon='ERROR')

        # Mode selector row
        row = layout.row(align=True)
        row.label(text="Mode:")
        row.prop(wm, "mixie_chat_quick_prompt_mode", text="")

        # Show generate type when GENERATE mode is active
        if wm.mixie_chat_quick_prompt_mode == 'GENERATE':
            row.prop(wm, "mixie_chat_quick_prompt_generate_type", text="")

        layout.separator()

        # Attachment controls row
        pending_count = len(scene.mixie_chat_pending_attachments)

        if pending_count > 0:
            box = layout.box()
            box.label(text=f"{pending_count} attachment(s) pending", icon='PAPERCLIP')

        row = layout.row(align=True)
        row.label(text="Attachments:")
        row.operator("mixie_chat.add_image_from_file", text="Add File", icon='FILEBROWSER')
        row.operator("mixie_chat.capture_screenshot", text="Screenshot", icon='IMAGE_PLANE')

        layout.separator()

        # Input field - uses window_manager property with TEXTEDIT_UPDATE for Enter detection
        row = layout.row()
        row.activate_init = True
        row.prop(wm, "mixie_chat_quick_prompt_input", text="Message")

    def execute(self, context):
        scene = context.scene
        wm = context.window_manager

        # Get message from window_manager property (used by UI) or operator property (direct call)
        message_text = wm.mixie_chat_quick_prompt_input.strip() or self.message.strip()

        if not message_text:
            self.report({'WARNING'}, "Please enter a message")
            return {'CANCELLED'}

        # Security: Validate message length
        if len(message_text) > MAX_MESSAGE_LENGTH:
            self.report(
                {'WARNING'},
                f"Message too long: {len(message_text)} chars (max {MAX_MESSAGE_LENGTH})"
            )
            return {'CANCELLED'}

        # Dev mode: simulate response without backend
        if DEV_MODE:
            return self._execute_dev_mode(context, message_text)

        session = get_session_manager()
        connection_manager = get_connection_manager()

        if not connection_manager.is_connected:
            self.report({'ERROR'}, "Not connected to server. Please connect in Mixie Chat.")
            return {'CANCELLED'}

        # Same predicate as the chat composer: idle / modifying / awaiting
        # input, or busy while the run is open (the prompt joins the run).
        allowed, reason = can_send(scene)
        if not allowed:
            self.report({'ERROR'}, reason or "Mixie Chat is not ready to receive messages")
            return {'CANCELLED'}

        # Mark the user as engaged so the "Hi I'm Mixie" greeting
        # doesn't reappear later — same flag the regular send path sets.
        scene.mixie_chat_user_has_engaged = True

        # Apply quick prompt mode to scene (so message uses correct mode)
        scene.mixie_chat_mode = wm.mixie_chat_quick_prompt_mode
        if wm.mixie_chat_quick_prompt_mode == 'GENERATE':
            # Generate mode never reaches the agent socket path — route through
            # the same sub-type handlers the footer send uses (they add the
            # user message, consume pending attachments and start the poll).
            # Previously this fell through to the agent stream below, so a
            # GENERATE quick prompt chatted with the agent instead of
            # generating.
            scene.mixie_chat_generate_type = wm.mixie_chat_quick_prompt_generate_type
            from . import generate_ops
            draft = scene.mixie_chat_input
            scene.mixie_chat_input = message_text
            try:
                result = generate_ops.execute_generate_mode(self, context)
            finally:
                scene.mixie_chat_input = draft
            if result == {'FINISHED'}:
                wm.mixie_chat_quick_prompt_input = ""
            return result

        # Use the full composer path, including image encoding, project rules,
        # interrupt answers and interjections. No separate transport owner.
        result = bpy.ops.mixie_chat.send_message(message_override=message_text)
        if result == {'FINISHED'}:
            wm.mixie_chat_quick_prompt_input = ""
        return result

    def _execute_dev_mode(self, context, message_text):
        """Execute in development mode without WebSocket"""
        scene = context.scene

        # Add user message
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = message_text

        # Add dummy response
        agent_msg = scene.mixie_chat_messages.add()
        agent_msg.sender = 'AGENT'
        agent_msg.text = get_dummy_response(message_text)

        # Trigger redraw
        redraw_chat_areas()

        # Clear input after successful send
        context.window_manager.mixie_chat_quick_prompt_input = ""

        logger.debug(f"Dev mode: Simulated response for: {message_text[:50]}...")
        self.report({'INFO'}, "Dev Mode: Message sent")
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_quick_prompt,
)
