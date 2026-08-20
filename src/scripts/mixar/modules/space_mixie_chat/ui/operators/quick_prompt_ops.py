# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Quick Prompt Operator for Mixie Chat

Global keyboard shortcut operator for quickly sending messages to Mixie Chat.
Uses HTTP/SSE for chat streaming.
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
from ...core.connection_manager import get_connection_manager
from ...core.jsonrpc_client import get_jsonrpc_client
from ...core.queue_processor import (
    queue_sse_event,
    queue_sse_error,
    queue_sse_complete,
)
from ...core.sse_handler import create_sse_handler
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
        elif not DEV_MODE and session.get_state(scene) != SessionState.IDLE:
            row = layout.row()
            row.alert = True
            row.label(text="Mixie Chat is busy", icon='ERROR')

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

        # Can only send when in IDLE, MODIFYING, or AWAITING_INPUT state
        if session.get_state(scene) not in (SessionState.IDLE, SessionState.MODIFYING, SessionState.AWAITING_INPUT):
            self.report({'ERROR'}, "Mixie Chat is not ready to receive messages")
            return {'CANCELLED'}

        # Mark the user as engaged so the "Hi I'm Mixie" greeting
        # doesn't reappear later — same flag the regular send path sets.
        scene.mixie_chat_user_has_engaged = True

        # Apply quick prompt mode to scene (so message uses correct mode)
        scene.mixie_chat_mode = wm.mixie_chat_quick_prompt_mode
        if wm.mixie_chat_quick_prompt_mode == 'GENERATE':
            # Generate mode never reaches the agent SSE path — route through
            # the same sub-type handlers the footer send uses (they add the
            # user message, consume pending attachments and start the poll).
            # Previously this fell through to the agent stream below, so a
            # GENERATE quick prompt chatted with the agent instead of
            # generating.
            scene.mixie_chat_generate_type = wm.mixie_chat_quick_prompt_generate_type
            scene.mixie_chat_input = message_text
            from . import generate_ops
            result = generate_ops.execute_generate_mode(self, context)
            if result == {'FINISHED'}:
                wm.mixie_chat_quick_prompt_input = ""
            return result

        project_context = None
        if scene.mixie_chat_mode == 'ADDON_PROJECT':
            if not str(getattr(scene, "mixie_addon_project_id", "") or ""):
                from mixar.modules.addon_project.ui.operators import (
                    prompt_for_addon_project_link,
                )
                prompt_for_addon_project_link(self)
                return {'CANCELLED'}
            try:
                from mixar.modules.addon_project.context import build_project_context
                project_context = build_project_context(scene)
            except Exception as exc:
                self.report({'ERROR'}, getattr(exc, "message", str(exc)))
                return {'CANCELLED'}

        # Add user message to history WITH attachments from pending
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = message_text

        # Copy pending attachments to message
        for pending_att in scene.mixie_chat_pending_attachments:
            msg_att = user_msg.attachments.add()
            msg_att.image_path = pending_att.image_path
            msg_att.image_source = pending_att.image_source
            msg_att.display_name = pending_att.display_name

        # Deselect moodboard images whose attachments we're about to
        # drop, so the moodboard sync doesn't re-attach them on the
        # next poll. See chat_ops.send_message for the rationale.
        try:
            from mixar.modules.moodboard.core.chat_sync import (
                deselect_all_moodboard_origin_attachments,
            )
            deselect_all_moodboard_origin_attachments(scene)
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "moodboard deselect on quick-prompt send skipped: %s",
                e, exc_info=True,
            )

        # Clear pending attachments after copying
        scene.mixie_chat_pending_attachments.clear()

        # Compose the wire message BEFORE start_session: project rules
        # ride along with the send that opens a NEW session, and a
        # mid-session rules change re-sends the current set under a
        # supersede header (see core/rules.py:compose_wire_message).
        from ...core.rules import compose_wire_message, mark_rules_sent
        wire_message = compose_wire_message(scene, message_text)

        # Start session
        session_id = session.start_session(scene, message_text)

        # Create SSE handler with queue callbacks
        # SSE events arrive on background thread - queue them for main thread processing
        base_url = get_server_url()
        target_scene_name = scene.name
        sse_handler = create_sse_handler(
            scene_name=target_scene_name,
            host=base_url,
            on_event=lambda event: queue_sse_event(event, target_scene_name),
            on_error=lambda error: queue_sse_error(error, target_scene_name),
            on_complete=lambda: queue_sse_complete(target_scene_name),
        )

        # Get auth token
        auth_token = _get_auth_token()

        # Use WebSocket client's connection_id to ensure chat uses the same ID
        # that was used to establish the WebSocket connection
        ws_client = get_jsonrpc_client()
        if not ws_client:
            self.report({'ERROR'}, "WebSocket not connected")
            session.set_error(scene)
            return {'CANCELLED'}

        # Start the SSE stream
        success = sse_handler.start_stream(
            message=wire_message,
            instance_id=ws_client.connection_id,
            session_id=session_id,
            auth_token=auth_token,
            project_context=project_context,
        )

        if not success:
            self.report({'ERROR'}, "Failed to start chat stream")
            session.set_error(scene)
            return {'CANCELLED'}

        # Stamp the sent-rules fingerprint only after a successful send
        # (see core/rules.py:mark_rules_sent).
        mark_rules_sent(scene)

        # Trigger UI redraw for all Mixie Chat spaces
        redraw_chat_areas()

        # Clear input after successful send
        wm.mixie_chat_quick_prompt_input = ""

        logger.info(f"Quick prompt message sent (mode={scene.mixie_chat_mode}) for session {session_id[:8]}...")
        self.report({'INFO'}, "Message sent to Mixie Chat")
        return {'FINISHED'}

    def _execute_dev_mode(self, context, message_text):
        """Execute in development mode without HTTP/SSE"""
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
