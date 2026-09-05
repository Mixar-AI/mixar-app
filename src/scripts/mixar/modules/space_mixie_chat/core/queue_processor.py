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
import time
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
# Serializes queue mutations that must be atomic across multiple Queue calls
# (notably per-scene cleanup). Producers wait on the condition when the queue
# is full, which releases this lock so cleanup can cancel the wait and the
# main-thread consumer can make progress.
_sse_queue_condition = threading.Condition()
_sse_queue_epoch = 0
_sse_scene_epochs: dict[str, int] = {}
_sse_timer_active = False
# The closure currently registered with bpy.app.timers (see
# _ensure_sse_timer_running for why a fresh closure is used per start).
_sse_timer_fn = None
_sse_drop_count = 0
# Tracks whether we're streaming long content (for adaptive timer frequency)
_streaming_content_long = False

# Ordinary events use bounded backpressure. If the UI cannot drain within the
# bound, rejecting the callback forces the SSE transport to re-attach and
# replay from its last accepted sequence instead of silently losing an event.
_SSE_EVENT_ENQUEUE_TIMEOUT = 1.0
_SSE_QUEUE_WAIT_SLICE = 0.1


def _queue_sse_item(item: tuple, timeout: Optional[float]) -> bool:
    """Enqueue an SSE item with cleanup-aware backpressure.

    ``timeout=None`` waits until capacity is available, unless queue/scene
    cleanup explicitly cancels the pending producer. Terminal and error items
    use that mode so queue saturation alone can never drop them.
    """
    scene_name = item[2]
    with _sse_queue_condition:
        queue_epoch = _sse_queue_epoch
        scene_epoch = _sse_scene_epochs.get(scene_name, 0)

    # Arm the consumer before waiting for capacity. Registering again after
    # the put closes the race with a timer that drains its final item while
    # this producer is waking up.
    if not _ensure_sse_timer_running():
        logger.error(
            "Cannot accept SSE item because the processing timer is unavailable"
        )
        return False
    deadline = None if timeout is None else time.monotonic() + timeout

    with _sse_queue_condition:
        while _sse_event_queue.full():
            if (
                queue_epoch != _sse_queue_epoch
                or scene_epoch != _sse_scene_epochs.get(scene_name, 0)
            ):
                return False

            wait_for = _SSE_QUEUE_WAIT_SLICE
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_for = min(wait_for, remaining)
            _sse_queue_condition.wait(timeout=wait_for)

        if (
            queue_epoch != _sse_queue_epoch
            or scene_epoch != _sse_scene_epochs.get(scene_name, 0)
        ):
            return False

        _sse_event_queue.put_nowait(item)

    if not _ensure_sse_timer_running():
        # The timer may have finished its empty tick between the pre-wait arm
        # and this put. If re-arming fails, retract an item that is still
        # queued so the caller can reject it and replay from the prior seq.
        # If the consumer already took it, downstream ownership was accepted.
        removed = False
        with _sse_queue_condition:
            cancelled = (
                queue_epoch != _sse_queue_epoch
                or scene_epoch != _sse_scene_epochs.get(scene_name, 0)
            )
            kept = []
            while True:
                try:
                    queued_item = _sse_event_queue.get_nowait()
                    if not removed and queued_item is item:
                        removed = True
                    else:
                        kept.append(queued_item)
                except queue.Empty:
                    break
            for queued_item in kept:
                _sse_event_queue.put_nowait(queued_item)
            if removed:
                _sse_queue_condition.notify_all()
        if removed or cancelled:
            return False
    return True


def _dequeue_sse_item_nowait() -> tuple:
    """Pop one item and wake producers waiting for queue capacity."""
    with _sse_queue_condition:
        item = _sse_event_queue.get_nowait()
        _sse_queue_condition.notify_all()
        return item


def queue_sse_event(event: SSEEvent, scene_name: str) -> bool:
    """Queue an SSE event for main thread processing.

    Called from SSE background thread.

    Args:
        event: SSEEvent to process
        scene_name: Name of the Blender scene this event belongs to
    """
    global _sse_drop_count

    # Legacy/server error payloads are terminal events even though they arrive
    # through the normal event callback, so they must not time out under load.
    timeout = None if event.event_type == "error" else _SSE_EVENT_ENQUEUE_TIMEOUT
    accepted = _queue_sse_item(("event", event, scene_name), timeout=timeout)
    if not accepted:
        _sse_drop_count += 1
        if _sse_drop_count % 10 == 1:
            logger.warning(
                f"[QUEUE] SSE event was not accepted (type={event.event_type}, "
                f"total_rejections={_sse_drop_count})"
            )
    return accepted


def queue_sse_error(error: str, scene_name: str) -> bool:
    """Queue an SSE error for main thread processing.

    Args:
        error: Error message string
        scene_name: Name of the Blender scene this error belongs to
    """
    return _queue_sse_item(("error", error, scene_name), timeout=None)


def queue_sse_complete(scene_name: str) -> bool:
    """Queue SSE completion for main thread processing.

    Args:
        scene_name: Name of the Blender scene this completion belongs to
    """
    return _queue_sse_item(("complete", None, scene_name), timeout=None)


def is_sse_timer_active() -> bool:
    """Check if the SSE processing timer is currently active.

    Used by animation_manager to skip redundant redraws when the SSE
    timer is already refreshing the UI at ~60fps.
    """
    return _sse_timer_active


def _ensure_sse_timer_running() -> bool:
    """Ensure the SSE processing timer is running.

    Thread-safe: called from SSE background thread via queue_sse_* functions.

    A fresh closure is registered per start (instead of _process_sse_queue
    itself): bpy timers are keyed by the callback object, so re-registering
    the same function while a previous registration is still completing its
    final ``return None`` can be silently dropped — stranding the queued
    event with no timer scheduled to process it.
    """
    global _sse_timer_active, _sse_timer_fn
    with _sse_timer_lock:
        if _sse_timer_active:
            return True

        def _tick():
            return _process_sse_queue()

        try:
            bpy.app.timers.register(_tick, first_interval=TIMER_INTERVAL)
            _sse_timer_fn = _tick
            _sse_timer_active = True
            return True
        except Exception as e:
            _sse_timer_active = False
            logger.error(f"Failed to start SSE timer: {e}")
            return False


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
            event_type, data, scene_name = _dequeue_sse_item_nowait()
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

    # The emptiness check and the flag clear must be atomic with respect to
    # the producer's flag check in _ensure_sse_timer_running: a put_nowait
    # landing between an unlocked check and the clear would see the flag
    # still True, skip re-arming the timer, and strand the final event
    # (stuck loader, session never returns to IDLE).
    with _sse_timer_lock:
        if not _sse_event_queue.empty():
            if _streaming_content_long:
                return TIMER_INTERVAL_THROTTLED
            return TIMER_INTERVAL
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
    global _sse_timer_active, _sse_drop_count, _streaming_content_long, _sse_timer_fn
    global _sse_queue_epoch

    with _sse_timer_lock:
        timer_fn = _sse_timer_fn
        _sse_timer_fn = None
        _sse_timer_active = False

    try:
        if timer_fn is not None and bpy.app.timers.is_registered(timer_fn):
            bpy.app.timers.unregister(timer_fn)
    except Exception:
        pass

    _streaming_content_long = False

    with _sse_queue_condition:
        _sse_queue_epoch += 1
        _sse_scene_epochs.clear()
        while True:
            try:
                _sse_event_queue.get_nowait()
            except queue.Empty:
                break
        _sse_queue_condition.notify_all()

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
    with _sse_queue_condition:
        _sse_scene_epochs[scene_name] = _sse_scene_epochs.get(scene_name, 0) + 1
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
            _sse_event_queue.put_nowait(item)
        _sse_queue_condition.notify_all()
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
            event_type, data, scene_name = _dequeue_sse_item_nowait()

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
        # Every streamed event belongs to the live agent turn. Mark it so the
        # executor groups/caps its undo checkpoints per turn (idempotent —
        # the turn begins with the first event and ends on stream
        # complete/error below, or on abort / file load).
        from .executor import get_executor
        get_executor().begin_agent_turn()

        data = event.data

        # In-band terminal error (backend refused the request before any slot
        # streaming — e.g. a text-only model can't accept an attached image, or
        # the connection wasn't found). These are non-slot legacy events; if we
        # don't handle them here they'd be silently dropped and the turn would
        # appear to cancel with no explanation. Surface as an agent bubble and
        # return to IDLE (the backend has already sent [DONE]).
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

        Unlike a mid-stream transport failure (``_handle_sse_error_internal``,
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
                f"SSE error - returning to IDLE "
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
            logger.info(f"SSE stream complete - returning to IDLE")
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
            logger.info(f"SSE stream complete - keeping state {current_state.value} (waiting for user input)")
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



# =============================================================================
# Development Mode: Execute singleton reset if module was reloaded
# =============================================================================
if _should_reset_singleton:
    logger.info("Development reload detected - resetting EventProcessor singleton")
    EventProcessor.reset_instance()
