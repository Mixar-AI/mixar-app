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


def send_cancel_request_async(session_id: str) -> None:
    """Send a cancel request to the backend in a background thread.

    Shared by New Chat and the history session switcher — both replace
    the live conversation and must stop any run still streaming on the
    old session first.
    """
    if not session_id:
        return

    import threading
    thread = threading.Thread(
        target=_send_cancel_request,
        args=(session_id,),
        daemon=True,
    )
    thread.start()


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
    bl_description = "Start a new chat (the current chat is saved to History)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        session = get_session_manager()
        scene = context.scene
        scene_name = scene.name
        from ...core.export_destination import clear_destination
        clear_destination(session.get_session_id(scene))

        # Cancel any running session before clearing
        old_session_id = session.get_session_id(scene)
        if old_session_id:
            from ...core.export_destination import clear_destination
            clear_destination(old_session_id)

        # 1. Stop any running SSE stream for this scene
        cleanup_sse_handler(scene_name)

        # 2. Drain queued SSE events
        from ...core.queue_processor import cleanup_sse_queue_for_scene
        cleanup_sse_queue_for_scene(scene_name)

        # 3. Flush queued tool scripts
        flush_executor_queue()

        # 4. Tell the backend to cancel the old session
        if old_session_id:
            send_cancel_request_async(old_session_id)

        # 5. Archive the current chat to local history before wiping it —
        #    New Chat is recoverable via the History popover
        #    (see core/chat_history.py). Best-effort: a failed archive
        #    must never block starting a fresh chat.
        try:
            from ...core.chat_history import archive_current
            archive_current(scene)
        except Exception as e:
            logger.error(f"Failed to archive chat before new session: {e}")
            self.report({'WARNING'}, "Could not save the chat to History")

        # Clear messages and incremental markdown cache
        scene.mixie_chat_messages.clear()
        scene.mixie_chat_input = ""
        # Re-arm the "Hi I'm Mixie" greeting for the fresh chat.
        if hasattr(scene, "mixie_chat_user_has_engaged"):
            scene.mixie_chat_user_has_engaged = False
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

        # The old session is gone — sweep any agentlane:* workspace scenes it
        # leaked (their backend removal scripts were dropped as stale).
        try:
            from ...core.lane_scene_sweep import schedule_lane_scene_sweep
            schedule_lane_scene_sweep()
        except Exception as e:
            logger.debug(f"lane scene sweep scheduling skipped: {e}")

        self.report({'INFO'}, "Started new chat session")
        return {'FINISHED'}


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
        state = session.get_state(scene)
        # BUSY: agent running.
        # AWAITING_INPUT: agent paused on a question (text / choice /
        # approval) — Escape should cancel it too, otherwise a prompt can
        # only be answered, never dismissed.
        if state in (SessionState.BUSY, SessionState.AWAITING_INPUT):
            return True
        # Defence-in-depth: allow abort from IDLE when a session_id exists.
        # Normally SSE errors keep state=BUSY, but edge cases may leave IDLE
        # while the backend is still running.
        if state == SessionState.IDLE:
            return bool(session.get_session_id(scene))
        return False

    def execute(self, context):
        session = get_session_manager()
        scene = context.scene
        scene_name = scene.name

        from ...core.export_destination import clear_destination
        clear_destination(session.get_session_id(scene))

        # 1. Stop SSE stream for this scene only
        cleanup_sse_handler(scene_name)

        # 2. Drain queued events for this scene
        from ...core.queue_processor import cleanup_sse_queue_for_scene
        cleanup_sse_queue_for_scene(scene_name)

        # 3. Flush queued tool scripts (global — scripts aren't scene-tagged)
        flush_executor_queue()

        # 3b. End the executor's undo turn: the drained queue may have held
        # the stream's complete/error event, so nothing else would end it and
        # the next turn would inherit this one's checkpoint budget.
        from ...core.executor import get_executor
        get_executor().end_agent_turn()

        # 4. Finalize in-progress loader bubble(s) on this scene
        self._finalize_loader_bubble(context)

        # 4b. Clear any pending interrupt prompt. If the agent was paused on a
        # request_user_input question (choice/approval buttons or a text
        # prompt), abort means the user is dismissing it — drop the buttons /
        # input affordance so a stale prompt can't be answered after the fact.
        # The backend /agent/cancel call below clears the matching server-side
        # interrupt, so the two stay in sync.
        self._clear_interrupt_prompt(context)

        # 4c. Settle the turn: collapse live narration -> "Thought for Ns",
        # finalize running steps, so a retry starts from a clean transcript.
        try:
            from ...core.slot_processor import finalize_turn
            finalize_turn(scene)
        except Exception as e:
            logger.debug(f"finalize_turn on abort skipped: {e}")

        # 4d. Stop means "that turn did not happen". The Scribble marks that
        # went with it were never acted on, so hand them back to the composer
        # as drafts: the retry ("continue", or the same request again) then
        # carries them. Without this the retry arrives with no marks and the
        # agent builds at the origin exactly as if nothing had been pointed at.
        try:
            from mixar.modules.scribble_mark.core import marks as mark_store
            reopened = mark_store.reopen_last_sent(scene)
            if reopened:
                logger.info(f"Scribble: reopened {reopened} mark(s) after stop")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"scribble mark reopen on abort skipped: {e}")

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

    @staticmethod
    def _clear_interrupt_prompt(context) -> None:
        """Drop any pending request_user_input prompt UI on user abort.

        Clears per-bubble ``action_items`` (choice/approval buttons) and
        ``input_type`` (text-input affordance) so the dismissed prompt can no
        longer be answered. Without this the C++ slot renderer keeps drawing the
        buttons after the session returns to IDLE, and clicking one would POST to
        /agent/input for an interrupt the backend has already cleared.
        """
        try:
            messages = context.scene.mixie_chat_messages
            for msg in messages:
                if getattr(msg, 'action_items', None) and len(msg.action_items):
                    msg.action_items.clear()
                if getattr(msg, 'input_type', ''):
                    msg.input_type = ''
        except Exception as e:
            logger.debug(f"_clear_interrupt_prompt skipped: {e}")

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


class MIXIE_CHAT_OT_resume_previous_task(Operator):
    """Adopt an orphaned turn: replay what was missed and follow it live."""

    bl_idname = "mixie_chat.resume_previous_task"
    bl_label = "Resume Previous Task"
    bl_description = (
        "The connection dropped while the agent was working. Reconnect to the "
        "running task and see everything it produced."
    )
    bl_options = {'REGISTER'}

    session_id: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        if context.scene is None or not context.scene.mixie_session_id:
            return False
        session = get_session_manager()
        return session.get_state(context.scene) == SessionState.IDLE

    def execute(self, context):
        import json as _json
        import uuid as _uuid

        from ...constants import TEMP_PLACEHOLDER_PREFIX
        from ...core.queue_processor import (
            queue_sse_complete,
            queue_sse_error,
            queue_sse_event,
        )
        from ...core.sse_handler import create_sse_handler
        from mixar.config.config import get_server_url

        scene = context.scene
        session = get_session_manager()
        target_session = self.session_id or session.get_session_id(scene)
        if not target_session:
            self.report({'WARNING'}, "No session to resume")
            return {'CANCELLED'}

        # A live handler for this scene means recovery is already owned by
        # its attach loop (or a stream is running) — never double-attach.
        from ...core.sse_handler import get_sse_handler
        existing = get_sse_handler(scene.name)
        if existing is not None and existing.is_running:
            self.report({'WARNING'}, "A task is already streaming")
            return {'CANCELLED'}

        # Show the turn as live again before attaching: loader bubble + BUSY,
        # the same optimistic UI a fresh send gets.
        self._reset_loader_bubbles(scene)
        placeholder = scene.mixie_chat_messages.add()
        placeholder.sender = 'AGENT'
        placeholder.bubble_id = f"{TEMP_PLACEHOLDER_PREFIX}{_uuid.uuid4().hex[:12]}"
        placeholder.loader_visible = True
        placeholder.loader_texts = _json.dumps(["Resuming previous task..."])
        try:
            from ...core.animation_manager import start_loader_animation
            start_loader_animation()
        except Exception:
            pass

        session.set_state(scene, SessionState.BUSY)

        base_url = get_server_url()
        target_scene_name = scene.name
        sse_handler = create_sse_handler(
            scene_name=target_scene_name,
            host=base_url,
            on_event=lambda event: queue_sse_event(event, target_scene_name),
            on_error=lambda error: queue_sse_error(error, target_scene_name),
            on_complete=lambda: queue_sse_complete(target_scene_name),
        )
        # Adopt the carried cursor when it belongs to this session; otherwise
        # follow from now (after_seq=-1 replays the WHOLE turn — a stale or
        # lost cursor would re-render everything as duplicates).
        after_seq = None
        if sse_handler._session_id == target_session and sse_handler._last_seq >= 0:
            after_seq = sse_handler._last_seq
        started = sse_handler.resume_stream(target_session, after_seq=after_seq)
        if not started:
            session.set_state(scene, SessionState.IDLE)
            self.report({'WARNING'}, "Could not resume the previous task")
            return {'CANCELLED'}

        from ...core.ui_utils import redraw_chat_areas
        redraw_chat_areas()
        logger.info("Resuming previous task for session %s", target_session[:8])
        return {'FINISHED'}

    @staticmethod
    def _reset_loader_bubbles(scene) -> None:
        """Settle stale loader bubbles left by the dropped turn's UI."""
        try:
            from ...constants import TEMP_PLACEHOLDER_PREFIX

            for i, m in enumerate(scene.mixie_chat_messages):
                if getattr(m, 'loader_visible', False):
                    m.loader_visible = False
            stale = [
                i for i, m in enumerate(scene.mixie_chat_messages)
                if getattr(m, 'bubble_id', '').startswith(TEMP_PLACEHOLDER_PREFIX)
            ]
            for idx in reversed(stale):
                scene.mixie_chat_messages.remove(idx)
        except Exception as e:
            logger.debug(f"_reset_loader_bubbles skipped: {e}")


classes = (
    MIXIE_CHAT_OT_connect,
    MIXIE_CHAT_OT_disconnect,
    MIXIE_CHAT_OT_new_session,
    MIXIE_CHAT_OT_dev_cycle_state,
    MIXIE_CHAT_OT_abort_session,
    MIXIE_CHAT_OT_resume_previous_task,
)
