# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Event processor for handling agent slot-based events.

All events use slot-based format with bubble_id containing declarative
UI slot updates (loader, content, ephemeral, todo, actions, images).

IMPORTANT: agent events arrive on a background thread, but Blender UI
operations must happen on the main thread. This module provides queue
functions to safely transfer events to the main thread via timers.
"""

from mixar.config.logging_config import get_logger
import json
from typing import Optional
import threading

import bpy

from ..constants import (
    SessionState,
    STREAMING_BATCH_LIMIT,
    TEMP_PLACEHOLDER_PREFIX,
    TIMER_INTERVAL,
)
from .session import get_session_manager
from .slot_processor import SlotEventProcessor, get_slot_processor
from .agent_events import AgentEvent
from .message_helpers import add_agent_message
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

class EventProcessor:
    """Processes agent events via slot-based architecture.

    All events use slot-based format with bubble_id. Processing
    is delegated to SlotEventProcessor which applies declarative
    slot updates to chat bubbles.
    """

    _instance: Optional["EventProcessor"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "EventProcessor":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:  # Double-checked locking
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize processor state."""
        self._session = get_session_manager()
        self._slot_processor = get_slot_processor()
        # Scene names whose current turn carried a `run_status` payload. A
        # turn that ends without one (older backend, chat-only turn) closes
        # the run on turn_end; one that did leaves the run as it reported it.
        self._run_status_seen: set = set()

    # ========================================================================
    # Typed (non-slot) payloads: run lifecycle + interjection acks
    # ========================================================================

    def _handle_typed_payload(self, data: dict, scene) -> bool:
        """Consume a typed payload; False leaves it to the slot pipeline.

        ``run_status`` (first payload of an orchestrated turn and again before
        its final ``complete``) is the run's authoritative open/closed signal;
        ``cancelled`` closes the run; ``joined`` / ``interjection_failed``
        settle the queued hint on the user bubble of an interjection.
        """
        kind = data.get("type")
        if kind == "run_status":
            self._run_status_seen.add(scene.name)
            self._session.set_run(
                scene, str(data.get("run_id") or ""), data.get("status") == "in_progress"
            )
            return True
        if kind == "cancelled":
            self._session.set_run(scene, "", False)
            return True
        if kind == "activity":
            # One per backend tool call: a step row (merged with the script
            # path's row on call_id) plus the images the call produced.
            from .steps_recorder import record_activity
            record_activity(scene, data)
            return True
        return False

    def _settle_run_on_complete(self, scene) -> None:
        """turn_end: close the run unless this turn reported its status."""
        if scene.name in self._run_status_seen:
            self._run_status_seen.discard(scene.name)
            return
        self._session.set_run(scene, "", False)

    # ========================================================================
    # agent Event Dispatch (called from timer on main thread)
    # ========================================================================

    def _handle_agent_event_internal(self, event: AgentEvent, scene) -> None:
        """
        Internal: Handle an agent event (called from main thread timer).

        All events use slot-based format with bubble_id.
        Does NOT call _redraw_ui() - the timer handles that after batch.
        """
        data = event.data

        # Run-lifecycle and interjection acks are bookkeeping, not part of the
        # undo turn — settle them before the turn bracket below.
        if isinstance(data, dict) and self._handle_typed_payload(data, scene):
            return

        # Every streamed event belongs to the live agent turn. Mark it so the
        # executor groups/caps its undo checkpoints per turn (idempotent —
        # the turn begins with the first event and ends on stream
        # complete/error below, or on abort / file load).
        from .executor import get_executor
        get_executor().begin_agent_turn()

        # In-band terminal error (backend refused the request before any slot
        # streaming — e.g. a text-only model can't accept an attached image, or
        # the connection wasn't found). These are non-slot legacy events; if we
        # don't handle them here they'd be silently dropped and the turn would
        # appear to cancel with no explanation. Surface as an agent bubble and
        # return to IDLE (the backend has already sent turn_end).
        is_inband_error = event.event_type == "error" or (
            isinstance(data, dict) and data.get("type") == "error"
        )
        if is_inband_error:
            message = ""
            if isinstance(data, dict):
                message = data.get("message") or ""
            self._handle_inband_error(
                message or "The request could not be completed.", scene
            )
            return

        if self._slot_processor.is_slot_event(data):
            self._slot_processor.apply_event(data, scene)
        else:
            logger.warning(f"Received non-slot event (type={event.event_type}), ignoring")

    def _handle_inband_error(self, message: str, scene) -> None:
        """Render a terminal in-band error as an agent bubble and go IDLE.

        Unlike a mid-stream transport failure (``_handle_agent_error_internal``,
        which may keep BUSY so Abort stays visible), an in-band error event is a
        clean refusal from the backend before any work started — always end the
        turn and return to IDLE.
        """
        from .executor import get_executor
        get_executor().end_agent_turn()

        from .animation_manager import stop_loader_animation
        stop_loader_animation()
        self._clear_loader_bubbles(scene)

        try:
            add_agent_message(scene, message)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error adding in-band error message to chat: {e}")

        self._session.set_state(scene, SessionState.IDLE)

    def handle_command_error(self, result, scene):
        """Display a confirmed command rejection, preserving typed credit actions."""
        from .credits_notice import is_credits_exhausted_error, add_credit_upgrade_chat_message
        message = result.get('message') or 'Message could not be delivered'
        data = result.get('data') or {}
        status = result.get('status_code') or data.get('status_code')
        if is_credits_exhausted_error(status, message):
            actions = data.get('data') or data
            add_credit_upgrade_chat_message(scene=scene, body=message,
                                            action_url=actions.get('action_url'))
            self._redraw_ui()
        else:
            self._handle_agent_error_internal(message, scene)

    def _handle_agent_error_internal(self, error_message: str, scene) -> None:
        """Handle agent stream-level error (called from main thread timer).

        HTTP errors (4xx/5xx) mean the backend rejected the request before
        streaming started — show the actual error and return to IDLE.

        Connection/timeout errors during an active stream keep BUSY so the
        Abort button stays visible (the backend may still be processing).
        """
        from .executor import get_executor
        get_executor().end_agent_turn()

        logger.error(f"agent stream error: {error_message}")

        # Stop any running slot animations
        from .animation_manager import stop_loader_animation
        stop_loader_animation()

        # Hide frozen loader bubbles so the UI doesn't show a stuck spinner
        self._clear_loader_bubbles(scene)

        # Classify the failure. HTTP errors and pre-stream failures
        # (connect/write timeouts, connection errors) mean the backend
        # never started processing — return to IDLE so the user can retry.
        # Mid-stream failures keep BUSY so Abort stays visible.
        error_message_lower = error_message.lower()
        is_http_error = error_message.startswith("HTTP ")
        is_pre_stream_error = (
            error_message.startswith("Connection error:")
            or "write operation timed out" in error_message_lower
            or "connect operation timed out" in error_message_lower
        )
        # Read timeouts are transient and noisy — backend may still be working.
        # Swallow the chat bubble but keep state cleanup so Abort stays visible.
        is_read_timeout = "read operation timed out" in error_message_lower
        user_message = self._extract_http_error_message(error_message) if is_http_error else error_message
        was_busy = self._session.get_state(scene) == SessionState.BUSY

        try:
            if is_read_timeout:
                pass  # suppress — see comment above
            elif is_http_error:
                # Credits exhausted (402): show the in-chat "Upgrade" message
                # instead of a plain error bubble. The backend also fires a
                # credit_upgrade WS push (toast + chat bubble); prefix-dedup
                # collapses the two into one bubble, and this branch doubles as
                # a main-thread-native fallback if the push doesn't arrive.
                details = self._parse_http_error(error_message)
                from .credits_notice import is_credits_exhausted_error
                if is_credits_exhausted_error(details.get("status"), user_message):
                    from .credits_notice import add_credit_upgrade_chat_message
                    add_credit_upgrade_chat_message(
                        scene=scene,
                        body=details.get("message") or user_message,
                        action_url=details.get("action_url"),
                    )
                else:
                    add_agent_message(scene, user_message)
            elif is_pre_stream_error:
                add_agent_message(
                    scene,
                    "Couldn't reach the server. Please check your connection and try again.",
                )
            elif was_busy:
                add_agent_message(
                    scene,
                    "Connection to the server was lost. "
                    "The agent may still be working — press Abort to cancel.",
                )
            else:
                add_agent_message(scene, error_message)
        except Exception as e:
            logger.error(f"Error adding error message to chat: {e}")

        if is_http_error or is_pre_stream_error or not was_busy:
            logger.info(
                f"agent error - returning to IDLE "
                f"(http_error={is_http_error}, pre_stream={is_pre_stream_error})"
            )
            self._session.set_state(scene, SessionState.IDLE)
            # Dead session: clean up leaked agentlane:* workspace scenes
            # (the sweep re-checks that no session is active before acting).
            try:
                from .lane_scene_sweep import schedule_lane_scene_sweep
                schedule_lane_scene_sweep()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"lane scene sweep scheduling skipped: {e}")
        else:
            # Keep BUSY so the Abort button stays visible — the backend may
            # still be running.  The user must explicitly abort.
            logger.info("agent error while BUSY - keeping BUSY (abort button stays)")

        self._redraw_ui()

    @staticmethod
    def _extract_http_error_message(error_message: str) -> str:
        """Extract a user-friendly message from an HTTP error string.

        Input format: "HTTP 400: {json_body}" or "HTTP 500: error text"
        Tries to parse JSON and extract the "message" field.
        """
        try:
            # Split off "HTTP NNN: " prefix
            _, _, body = error_message.partition(": ")
            if body:
                data = json.loads(body)
                if isinstance(data, dict) and "message" in data:
                    return data["message"]
        except (json.JSONDecodeError, ValueError):
            pass
        return error_message

    @staticmethod
    def _parse_http_error(error_message: str) -> dict:
        """Parse a "HTTP NNN: {json_body}" error into its parts.

        Returns a dict with ``status`` (int or None), ``message``, and the
        credit CTA fields ``action_url`` / ``action_label`` when the body
        carries them. Handles both the flat ORJSONResponse body
        ({status, message, data}) and the HTTPException body ({detail: {...}}).
        """
        result = {
            "status": None,
            "message": error_message,
            "action_url": None,
            "action_label": None,
        }
        try:
            prefix, _, body = error_message.partition(": ")
            parts = prefix.split()
            if len(parts) == 2 and parts[0] == "HTTP" and parts[1].isdigit():
                result["status"] = int(parts[1])
            if body:
                data = json.loads(body)
                if isinstance(data, dict):
                    inner = data.get("detail") if isinstance(data.get("detail"), dict) else data
                    if isinstance(inner, dict):
                        if inner.get("message"):
                            result["message"] = inner["message"]
                        cta = inner.get("data")
                        if isinstance(cta, dict):
                            result["action_url"] = cta.get("action_url")
                            result["action_label"] = cta.get("action_label")
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        return result

    def _clear_loader_bubbles(self, scene) -> None:
        """Hide loader indicators and remove temp placeholder bubbles.

        Temp placeholders (created before the agent request for instant
        feedback) would remain as invisible ghost entries if no real
        agent event ever replaces them (e.g. HTTP 400 error).
        """
        try:
            if not scene or not hasattr(scene, 'mixie_chat_messages'):
                return
            messages = scene.mixie_chat_messages
            # Remove temp placeholders in reverse to preserve indices
            to_remove = []
            for i, msg in enumerate(messages):
                if getattr(msg, 'loader_visible', False):
                    msg.loader_visible = False
                bid = getattr(msg, 'bubble_id', '')
                if bid.startswith(TEMP_PLACEHOLDER_PREFIX):
                    to_remove.append(i)
            for idx in reversed(to_remove):
                messages.remove(idx)
        except Exception as e:
            logger.debug(f"_clear_loader_bubbles skipped: {e}")

    def _handle_agent_complete_internal(self, scene) -> None:
        """Handle agent stream completion (called from main thread timer)."""
        # The stream is over: end the executor's undo turn whether the session
        # settles to IDLE or pauses for input (the user's answer starts a new
        # stream, and with it a new turn / fresh checkpoint budget).
        from .executor import get_executor
        get_executor().end_agent_turn()

        # Don't override AWAITING_INPUT or MODIFYING states
        # (agent is paused on a question — text, choice, or approval —
        # so the pill keeps reading "Awaiting input" instead of "Idle")
        current_state = self._session.get_state(scene)
        if current_state not in (SessionState.AWAITING_INPUT, SessionState.MODIFYING):
            logger.info(f"agent stream complete - returning to IDLE")
            self._session.set_state(scene, SessionState.IDLE)
            # Collapse live narration -> "Thought for Ns" and settle steps.
            try:
                from .slot_processor import finalize_turn
                finalize_turn(scene)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"finalize_turn on complete skipped: {e}")
            # Crash-safe history: upsert the settled transcript so the
            # conversation is recoverable from the History popover even
            # if the app quits before New Chat is ever clicked.
            try:
                from .chat_history import archive_current
                archive_current(scene)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"history upsert on complete skipped: {e}")

            # Session settled to IDLE — remove any agentlane:* workspace
            # scenes whose backend removal scripts never landed (dropped as
            # stale once the session went inactive). Fail-soft, main thread.
            try:
                from .lane_scene_sweep import schedule_lane_scene_sweep
                schedule_lane_scene_sweep()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"lane scene sweep scheduling skipped: {e}")

            # Show feedback only on the newest completed agent response.
            self._show_feedback_on_last_agent_message(scene)
        else:
            logger.info(f"agent stream complete - keeping state {current_state.value} (waiting for user input)")
        self._settle_run_on_complete(scene)
        self._redraw_ui()

    @staticmethod
    def _show_feedback_on_last_agent_message(scene) -> None:
        """Set feedback_visible=True on the most recent agent message with content."""
        if not scene or not hasattr(scene, 'mixie_chat_messages'):
            return
        messages = scene.mixie_chat_messages
        # Only the latest response should offer feedback. Clear stale flags
        # before selecting the newest eligible agent message.
        for msg in messages:
            if getattr(msg, 'feedback_visible', False):
                msg.feedback_visible = False

        # Walk backwards to find the last agent message with content.
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.sender != 'AGENT':
                continue
            has_content = bool(
                getattr(msg, 'content', '') or getattr(msg, 'text', '')
            )
            if has_content and getattr(msg, 'bubble_id', ''):
                msg.feedback_visible = True
                logger.debug(
                    f"Feedback enabled on bubble_id={msg.bubble_id}"
                )
                return

    # ========================================================================
    # UI Helpers
    # ========================================================================

    def _trigger_redraw(self) -> None:
        """Trigger UI redraw for MIXIE_CHAT areas."""
        redraw_chat_areas()

    def _redraw_ui(self) -> None:
        """Force UI redraw for all Mixie chat editor and bubble surfaces."""
        try:
            redraw_chat_areas()
        except Exception as e:
            logger.warning(f"Could not redraw UI: {e}")

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            cls._instance._initialize()

    @classmethod
    def reset_instance(cls) -> None:
        """Force reset singleton instance (used during development reloads)."""
        if cls._instance is not None:
            logger.info("Resetting EventProcessor singleton (development reload)")
            cls._instance = None


def get_event_processor() -> EventProcessor:
    """Get the global EventProcessor singleton."""
    return EventProcessor()





def drain_pending_events() -> int:
    """Render already-received events before executing a main-thread tool."""
    from . import turn_events
    with turn_events._LOCK:
        count = len(turn_events._inbox)
    turn_events._drain()
    return min(count, 64)


def cleanup_event_queue():
    from .turn_events import shutdown
    shutdown()


def cleanup_event_queue_for_scene(scene_name):
    from .turn_events import drop_scene
    drop_scene(scene_name)
