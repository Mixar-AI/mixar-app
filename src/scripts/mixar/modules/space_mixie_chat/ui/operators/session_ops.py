# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Session management operators for Mixie Chat.

Provides operators for connection management using JSON-RPC WebSocket.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import get_connection_manager, get_session_manager
from ...core import populate_dev_session, DevDataProvider
from ...core.sse_handler import cleanup_sse_handler
from ...core.main_thread_executor import cleanup as flush_executor_queue
from ...core.message_helpers import get_auth_token
from ...constants import DEV_MODE, SessionState

logger = get_logger(__name__)


class MIXIE_CHAT_OT_connect(Operator):
    """Connect to the WebSocket server"""
    bl_idname = "mixie_chat.connect"
    bl_label = "Connect"
    bl_description = "Connect to the Mixie agent server"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        # Must be logged in to connect
        if not context.window_manager or not context.window_manager.mixie_chat_is_logged_in:
            return False

        session = get_session_manager()
        return session.get_state(context.scene) == SessionState.OFFLINE

    def execute(self, context):
        session = get_session_manager()

        # Dev mode: bypass WebSocket and populate with dummy data
        if DEV_MODE:
            return self._execute_dev_mode(context, session)

        # Use ConnectionManager for connection
        manager = get_connection_manager()

        # Initialize if needed
        if not manager.instance_id:
            manager.initialize()

        # Connect
        if manager.connect():
            self.report({'INFO'}, "Connecting to server...")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to connect")
            return {'CANCELLED'}

    def _execute_dev_mode(self, context, session):
        """Execute in development mode with dummy data."""
        logger.debug("DEV_MODE enabled - bypassing WebSocket connection")

        # Populate with dummy data in IDLE state
        populate_dev_session(session, context.scene, SessionState.IDLE)

        self.report({'INFO'}, "Dev Mode: Connected with dummy data")
        return {'FINISHED'}


class MIXIE_CHAT_OT_disconnect(Operator):
    """Disconnect from the WebSocket server"""
    bl_idname = "mixie_chat.disconnect"
    bl_label = "Disconnect"
    bl_description = "Disconnect from the Mixie agent server"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        session = get_session_manager()
        return session.get_state(context.scene) != SessionState.OFFLINE

    def execute(self, context):
        session = get_session_manager()

        # Dev mode: just reset state and clear messages
        if DEV_MODE:
            session.clear(context.scene)
            context.scene.mixie_chat_messages.clear()
            DevDataProvider.reset_state_cycle()
            self.report({'INFO'}, "Dev Mode: Disconnected")
            return {'FINISHED'}

        # Use ConnectionManager for disconnection
        manager = get_connection_manager()
        manager.disconnect()

        self.report({'INFO'}, "Disconnected from server")
        return {'FINISHED'}


class MIXIE_CHAT_OT_new_session(Operator):
    """Start a new chat session"""
    bl_idname = "mixie_chat.new_session"
    bl_label = "New Chat"
    bl_description = "Clear chat and start a new session"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        session = get_session_manager()
        scene = context.scene
        scene_name = scene.name

        # Cancel any running session before clearing
        old_session_id = session.get_session_id(scene)

        # 1. Stop any running SSE stream for this scene
        cleanup_sse_handler(scene_name)

        # 2. Drain queued SSE events
        from ...core.queue_processor import cleanup_sse_queue_for_scene
        cleanup_sse_queue_for_scene(scene_name)

        # 3. Flush queued tool scripts
        flush_executor_queue()

        # 4. Tell the backend to cancel the old session
        if old_session_id:
            self._send_cancel_request_async(old_session_id)

        # Clear messages and incremental markdown cache
        scene.mixie_chat_messages.clear()
        scene.mixie_chat_input = ""
        from ...core.markdown_parser import clear_incremental_cache
        clear_incremental_cache()

        # Dev mode: reset state cycle
        if DEV_MODE:
            DevDataProvider.reset_state_cycle()

        # Reset session (keep connected if connected)
        if session.is_connected(scene):
            session.clear_streaming()
            session.clear_session_id(scene)  # Force new session_id on next message
            session.set_connected(scene)
        else:
            session.clear_session_id(scene)
            session.set_state(scene, SessionState.OFFLINE)

        self.report({'INFO'}, "Started new chat session")
        return {'FINISHED'}

    @staticmethod
    def _send_cancel_request_async(session_id: str) -> None:
        """Send cancel request to backend in background thread."""
        if not session_id:
            return

        import threading
        thread = threading.Thread(
            target=MIXIE_CHAT_OT_new_session._send_cancel_request,
            args=(session_id,),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _send_cancel_request(session_id: str) -> None:
        """Send cancel request to backend (runs in background thread)."""
        try:
            import httpx
            from mixar.config.config import get_server_url

            base_url = get_server_url()
            auth_token = get_auth_token()

            if not auth_token:
                logger.warning("No auth token available for cancel request")
                return

            url = f"{base_url}/api/v1/blender/agent/cancel"
            headers = {"Authorization": f"Bearer {auth_token}"}
            payload = {"session_id": session_id}

            with httpx.Client(timeout=5.0) as client:
                response = client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    logger.info(f"Backend session cancelled: {session_id[:8]}")
                else:
                    logger.warning(
                        f"Failed to cancel backend session: HTTP {response.status_code}"
                    )
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error during cancel request: {e}")
        except Exception as e:
            logger.error(f"Failed to send cancel request: {e}")


class MIXIE_CHAT_OT_dev_cycle_state(Operator):
    """Cycle through states for UI testing (Dev Mode only)"""
    bl_idname = "mixie_chat.dev_cycle_state"
    bl_label = "Cycle State"
    bl_description = "Cycle through different session states for UI testing"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return DEV_MODE and get_session_manager().is_connected(context.scene)

    def execute(self, context):
        session = get_session_manager()
        next_state = DevDataProvider.get_next_state()

        # Populate with dummy data for the new state
        populate_dev_session(session, context.scene, next_state)

        self.report({'INFO'}, f"Dev Mode: Switched to {next_state.value}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_abort_session(Operator):
    """Abort the current session."""

    bl_idname = "mixie_chat.abort_session"
    bl_label = "Abort"
    bl_description = "Stop the agent"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False
        session = get_session_manager()
        scene = context.scene
        if session.get_state(scene) == SessionState.BUSY:
            return True
        # Defence-in-depth: allow abort from IDLE when a session_id exists.
        # Normally SSE errors keep state=BUSY, but edge cases may leave IDLE
        # while the backend is still running.
        if session.get_state(scene) == SessionState.IDLE:
            return bool(session.get_session_id(scene))
        return False

    def execute(self, context):
        session = get_session_manager()
        scene = context.scene
        scene_name = scene.name

        # 1. Stop SSE stream for this scene only
        cleanup_sse_handler(scene_name)

        # 2. Drain queued events for this scene
        from ...core.queue_processor import cleanup_sse_queue_for_scene
        cleanup_sse_queue_for_scene(scene_name)

        # 3. Flush queued tool scripts (global — scripts aren't scene-tagged)
        flush_executor_queue()

        # 4. Finalize in-progress loader bubble(s) on this scene
        self._finalize_loader_bubble(context)

        # 5. Send abort to backend
        self._send_abort_request_async(session.get_session_id(scene))

        # 6. Reset state
        session.clear_streaming()
        session.set_connected(scene)

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE_CHAT':
                    area.tag_redraw()

        logger.info("Session aborted by user")
        self.report({'INFO'}, "Session aborted")
        return {'FINISHED'}

    @staticmethod
    def _finalize_loader_bubble(context) -> None:
        """Finalize the in-progress loader bubble on user abort.

        Empty (loader-only) bubbles are removed. Bubbles that already have
        streamed content keep their content with the loader hidden and an
        italic *Stopped* marker appended so the user sees the response was
        cut short rather than a backend error.
        """
        stopped_marker = "*Stopped*"
        try:
            messages = context.scene.mixie_chat_messages
            to_remove = []
            for i, msg in enumerate(messages):
                if not getattr(msg, 'loader_visible', False):
                    continue
                content = getattr(msg, 'content', '') or ''
                if not content.strip():
                    to_remove.append(i)
                    continue
                msg.loader_visible = False
                if stopped_marker not in content:
                    msg.content = content.rstrip() + "\n\n" + stopped_marker
            for idx in reversed(to_remove):
                messages.remove(idx)
        except Exception as e:
            logger.debug(f"_finalize_loader_bubble skipped: {e}")

    def _send_abort_request_async(self, session_id: str) -> None:
        """Send abort request to backend in background thread."""
        if not session_id:
            return

        import threading
        thread = threading.Thread(
            target=self._send_abort_request,
            args=(session_id,),
            daemon=True
        )
        thread.start()

    def _send_abort_request(self, session_id: str) -> None:
        """Send abort request to backend (runs in background thread)."""
        try:
            import httpx
            from mixar.config.config import get_server_url

            base_url = get_server_url()
            auth_token = get_auth_token()

            if not auth_token:
                logger.warning("No auth token available for abort request")
                return

            url = f"{base_url}/api/v1/blender/agent/cancel"
            headers = {"Authorization": f"Bearer {auth_token}"}
            payload = {"session_id": session_id}

            # Use timeout to prevent hanging
            with httpx.Client(timeout=5.0) as client:
                response = client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    logger.info(f"Backend session aborted: {session_id[:8]}")
                else:
                    logger.warning(
                        f"Failed to abort backend session: HTTP {response.status_code}"
                    )
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error during abort request: {e}")
        except Exception as e:
            logger.error(f"Failed to send abort request: {e}")


classes = (
    MIXIE_CHAT_OT_connect,
    MIXIE_CHAT_OT_disconnect,
    MIXIE_CHAT_OT_new_session,
    MIXIE_CHAT_OT_dev_cycle_state,
    MIXIE_CHAT_OT_abort_session,
)
