# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Event processor for handling SSE slot-based events.

All events use slot-based format with bubble_id containing declarative
UI slot updates (loader, content, ephemeral, todo, actions, images).

IMPORTANT: SSE events arrive on a background thread, but Blender UI
operations must happen on the main thread. This module provides queue
functions to safely transfer events to the main thread via timers.
"""

from mixar.config.logging_config import get_logger
import json
import queue
from typing import Optional
import threading

import bpy

from ..constants import (
    SessionState,
    STREAMING_BATCH_LIMIT,
    TEMP_PLACEHOLDER_PREFIX,
    TIMER_INTERVAL,
    TIMER_INTERVAL_THROTTLED,
    TIMER_THROTTLE_CONTENT_THRESHOLD,
)
from .session import get_session_manager
from .slot_processor import SlotEventProcessor, get_slot_processor
from .sse_handler import SSEEvent
from .message_helpers import add_agent_message
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# =============================================================================
# Development Mode: Auto-reload detection
# =============================================================================
import sys
if "queue_processor" in sys.modules:
    _should_reset_singleton = True
else:
    _should_reset_singleton = False

# =============================================================================
# SSE Event Queue for Main Thread Processing
# =============================================================================

_sse_event_queue: queue.Queue = queue.Queue(maxsize=1000)
_sse_timer_lock = threading.Lock()
_sse_timer_active = False
_sse_drop_count = 0
# Tracks whether we're streaming long content (for adaptive timer frequency)
_streaming_content_long = False


def queue_sse_event(event: SSEEvent, scene_name: str) -> None:
    """Queue an SSE event for main thread processing.

    Called from SSE background thread.

    Args:
        event: SSEEvent to process
        scene_name: Name of the Blender scene this event belongs to
    """
    global _sse_drop_count

    try:
        _sse_event_queue.put_nowait(("event", event, scene_name))
    except queue.Full:
        _sse_drop_count += 1
        if event.event_type == "error":
            # Never drop error events - drain oldest non-error to make room
            try:
                _sse_event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                _sse_event_queue.put_nowait(("event", event, scene_name))
            except queue.Full:
                pass  # Queue still full after drain, truly cannot enqueue
            logger.warning("Dropped oldest event to prioritize ERROR event")
        else:
            if _sse_drop_count % 10 == 1:
                logger.warning(
                    f"[QUEUE] SSE event queue full, dropping event (type={event.event_type}, "
                    f"total_drops={_sse_drop_count})"
                )
            return
    _ensure_sse_timer_running()


def queue_sse_error(error: str, scene_name: str) -> None:
    """Queue an SSE error for main thread processing.

    Args:
        error: Error message string
        scene_name: Name of the Blender scene this error belongs to
    """
    try:
        _sse_event_queue.put_nowait(("error", error, scene_name))
    except queue.Full:
        logger.warning("SSE event queue full, dropping error event")
        return
    _ensure_sse_timer_running()


def queue_sse_complete(scene_name: str) -> None:
    """Queue SSE completion for main thread processing.

    Args:
        scene_name: Name of the Blender scene this completion belongs to
    """
    try:
        _sse_event_queue.put_nowait(("complete", None, scene_name))
    except queue.Full:
        logger.warning("SSE event queue full, dropping complete event")
        return
    _ensure_sse_timer_running()


def is_sse_timer_active() -> bool:
    """Check if the SSE processing timer is currently active.

    Used by animation_manager to skip redundant redraws when the SSE
    timer is already refreshing the UI at ~60fps.
    """
    return _sse_timer_active


def _ensure_sse_timer_running() -> None:
    """Ensure the SSE processing timer is running.

    Thread-safe: called from SSE background thread via queue_sse_* functions.
    """
    global _sse_timer_active
    with _sse_timer_lock:
        if not _sse_timer_active:
            try:
                if not bpy.app.timers.is_registered(_process_sse_queue):
                    bpy.app.timers.register(_process_sse_queue, first_interval=TIMER_INTERVAL)
                    _sse_timer_active = True
            except Exception as e:
                if bpy.app.timers.is_registered(_process_sse_queue):
                    bpy.app.timers.unregister(_process_sse_queue)
                _sse_timer_active = False
                logger.error(f"Failed to start SSE timer: {e}")


def _process_sse_queue() -> Optional[float]:
    """Timer callback - process SSE slot events on main thread.

    Uses smart batching:
    - content.append events: up to STREAMING_BATCH_LIMIT per tick
      to avoid blocking Blender's main loop during text streaming.
    - State-changing slots (loader, actions, todo, images): trigger
      an immediate break so the UI redraws before next event.
    - General batch limit: 50 events per tick.

    Adaptive frequency: runs at 60fps for short content, drops to 30fps
    when streaming long messages to yield main thread time to Blender's
    event loop (prevents pinch-to-zoom / input starvation).
    """
    global _sse_timer_active, _streaming_content_long

    processor = get_event_processor()
    processed = False
    event_count = 0
    content_append_count = 0

    while True:
        try:
            event_type, data, scene_name = _sse_event_queue.get_nowait()
            event_count += 1

            scene = bpy.data.scenes.get(scene_name)
            if scene is None:
                from .sse_handler import cleanup_sse_handler
                cleanup_sse_handler(scene_name)
                continue

            if event_type == "event":
                processor._handle_sse_event_internal(data, scene)

                # Smart batching for slot events:
                # content.append (streaming text) - batch limit to avoid blocking main loop
                # loader/actions/todo changes - break after for immediate UI redraw
                event_data = data.data
                if "content" in event_data and "append" in event_data.get("content", {}):
                    content_append_count += 1
                    if content_append_count >= STREAMING_BATCH_LIMIT:
                        processed = True
                        break
                elif any(k in event_data for k in ("loader", "actions", "todo", "images")):
                    # State-changing slots - break for immediate redraw
                    processed = True
                    break
            elif event_type == "error":
                processor._handle_sse_error_internal(data, scene)
            elif event_type == "complete":
                processor._handle_sse_complete_internal(scene)
                _streaming_content_long = False  # Reset throttle on stream end

            processed = True

            if event_count >= 50:
                break

        except queue.Empty:
            break
        except Exception as e:
            logger.error(f"[QUEUE] Error processing SSE event: {e}", exc_info=True)
            break

    if processed:
        processor._redraw_ui()

        # Adaptive frequency: check if any active bubble has long content
        if content_append_count > 0:
            _streaming_content_long = _check_content_length_threshold()

    if not _sse_event_queue.empty():
        if _streaming_content_long:
            return TIMER_INTERVAL_THROTTLED
        return TIMER_INTERVAL

    with _sse_timer_lock:
        _sse_timer_active = False
    _streaming_content_long = False
    return None


def _check_content_length_threshold() -> bool:
    """Check if any active streaming bubble exceeds the content length threshold.

    Iterates all scenes to find long content, since events may target any scene.
    Returns True if timer should be throttled to 30fps.
    """
    try:
        for scene in bpy.data.scenes:
            if not hasattr(scene, 'mixie_chat_messages'):
                continue
            messages = scene.mixie_chat_messages
            count = len(messages)
            for i in range(max(0, count - 3), count):
                msg = messages[i]
                if msg.sender == 'AGENT' and len(msg.content) > TIMER_THROTTLE_CONTENT_THRESHOLD:
                    return True
    except Exception:
        pass
    return False


def cleanup_sse_queue() -> None:
    """Clean up SSE queue and timer. Call on disconnect/shutdown."""
    global _sse_timer_active, _sse_drop_count, _streaming_content_long

    try:
        if bpy.app.timers.is_registered(_process_sse_queue):
            bpy.app.timers.unregister(_process_sse_queue)
    except Exception:
        pass

    with _sse_timer_lock:
        _sse_timer_active = False

    _streaming_content_long = False

    while not _sse_event_queue.empty():
        try:
            _sse_event_queue.get_nowait()
        except queue.Empty:
            break

    if _sse_drop_count > 0:
        logger.info(f"SSE queue cleanup: {_sse_drop_count} events were dropped this session")
    _sse_drop_count = 0

    # Clear incremental markdown cache
    from .markdown_parser import clear_incremental_cache
    clear_incremental_cache()

    logger.debug("SSE queue cleaned up")


def cleanup_sse_queue_for_scene(scene_name: str) -> None:
    """Remove all queued events for a specific scene.
    Events for other scenes are preserved."""
    kept = []
    drained = 0
    while True:
        try:
            item = _sse_event_queue.get_nowait()
            if item[2] == scene_name:
                drained += 1
            else:
                kept.append(item)
        except queue.Empty:
            break
    for item in kept:
        try:
            _sse_event_queue.put_nowait(item)
        except queue.Full:
            break
    if drained > 0:
        logger.debug(f"Drained {drained} events for scene '{scene_name}'")


def reset_sse_drop_count() -> None:
    """Reset the SSE drop counter. Called when a new stream session starts."""
    global _sse_drop_count
    if _sse_drop_count > 0:
        logger.info(f"SSE drop count reset (was {_sse_drop_count})")
    _sse_drop_count = 0


def drain_pending_events() -> int:
    """Process all pending SSE events synchronously (main thread only).

    Called from the script executor to ensure planning text and state
    transitions are processed before script execution blocks the main thread.

    Returns:
        Number of events processed.
    """
    processor = get_event_processor()
    count = 0

    while count < 100:  # Safety cap
        try:
            event_type, data, scene_name = _sse_event_queue.get_nowait()

            scene = bpy.data.scenes.get(scene_name)
            if scene is None:
                count += 1
                continue

            count += 1
            if event_type == "event":
                processor._handle_sse_event_internal(data, scene)
            elif event_type == "error":
                processor._handle_sse_error_internal(data, scene)
            elif event_type == "complete":
                processor._handle_sse_complete_internal(scene)
        except queue.Empty:
            break
        except Exception as e:
            logger.error(f"Error draining SSE event: {e}", exc_info=True)
            break

    if count > 0:
        processor._redraw_ui()
        logger.debug(f"Drained {count} SSE events before script execution")

    return count


class EventProcessor:
    """Processes SSE events via slot-based architecture.

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

    # ========================================================================
    # SSE Event Dispatch (called from timer on main thread)
    # ========================================================================

    def _handle_sse_event_internal(self, event: SSEEvent, scene) -> None:
        """
        Internal: Handle an SSE event (called from main thread timer).

        All events use slot-based format with bubble_id.
        Does NOT call _redraw_ui() - the timer handles that after batch.
        """
        data = event.data

        if self._slot_processor.is_slot_event(data):
            self._slot_processor.apply_event(data, scene)
        else:
            logger.warning(f"Received non-slot event (type={event.event_type}), ignoring")

    def _handle_sse_error_internal(self, error_message: str, scene) -> None:
        """Handle SSE stream-level error (called from main thread timer).

        HTTP errors (4xx/5xx) mean the backend rejected the request before
        streaming started — show the actual error and return to IDLE.

        Connection/timeout errors during an active stream keep BUSY so the
        Abort button stays visible (the backend may still be processing).
        """
        from .executor import get_executor
        get_executor().end_agent_turn()

        logger.error(f"SSE stream error: {error_message}")

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
                f"SSE error - returning to IDLE "
                f"(http_error={is_http_error}, pre_stream={is_pre_stream_error})"
            )
            self._session.set_state(scene, SessionState.IDLE)
        else:
            # Keep BUSY so the Abort button stays visible — the backend may
            # still be running.  The user must explicitly abort.
            logger.info("SSE error while BUSY - keeping BUSY (abort button stays)")

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

    def _clear_loader_bubbles(self, scene) -> None:
        """Hide loader indicators and remove temp placeholder bubbles.

        Temp placeholders (created before the SSE request for instant
        feedback) would remain as invisible ghost entries if no real
        SSE event ever replaces them (e.g. HTTP 400 error).
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

    def _handle_sse_complete_internal(self, scene) -> None:
        """Handle SSE stream completion (called from main thread timer)."""
        # Don't override AWAITING_INPUT or MODIFYING states
        # (agent is waiting for user to provide text input)
        current_state = self._session.get_state(scene)
        if current_state not in (SessionState.AWAITING_INPUT, SessionState.MODIFYING):
            logger.info(f"SSE stream complete - returning to IDLE")
            self._session.set_state(scene, SessionState.IDLE)
            # Collapse live narration -> "Thought for Ns" and settle steps.
            try:
                from .slot_processor import finalize_turn
                finalize_turn(scene)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"finalize_turn on complete skipped: {e}")
        else:
            logger.info(f"SSE stream complete - keeping state {current_state.value} (waiting for user input)")
        self._redraw_ui()

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



# =============================================================================
# Development Mode: Execute singleton reset if module was reloaded
# =============================================================================
if _should_reset_singleton:
    logger.info("Development reload detected - resetting EventProcessor singleton")
    EventProcessor.reset_instance()
