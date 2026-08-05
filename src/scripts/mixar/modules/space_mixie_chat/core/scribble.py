# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Scribble — handwriting strokes to text in the chat composer.

The C++ ink overlay captures the strokes and, ~``SCRIBBLE_IDLE_COMMIT_MS``
after the pen lifts, dispatches ``mixie_chat.ink_commit`` with them as JSON
and clears its canvas. Everything from that point is here: validate the
payload, rasterize it (``scribble_raster``), POST it to the handwriting
endpoint, and append the transcription to ``scene.mixie_chat_input``.

**One request at a time, FIFO.** A user writing continuously produces a new
batch every pause, and the transcriptions must land in the order they were
written — a second request racing the first would reorder the sentence. Later
batches queue behind the in-flight one.

The hint is deliberately resolved at POST time, not when the batch is queued:
a queued batch continues the sentence the *previous* batch just appended, and
a hint snapshotted at enqueue time would describe the composer as it was
before that text existed.

``bpy`` is reached only through late imports so the standalone test suite can
exercise the parsing, spacing and queue logic outside Blender.
"""

import json
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    CHAT_INPUT_MAXLEN,
    SCRIBBLE_COMMIT_MAXLEN,
    SCRIBBLE_HINT_TAIL_CHARS,
    SCRIBBLE_MAX_POINTS,
    SCRIBBLE_MAX_STROKES,
)

logger = get_logger(__name__)

# Single in-flight request plus the batches waiting behind it, oldest first.
# Each pending entry is (scene, png_bytes) — the strokes are rasterized when
# they are handed over, so a malformed batch fails at the operator rather
# than minutes later when its turn comes up.
_in_flight = False
_pending: List[Tuple[object, bytes]] = []

# Delivery-dedup token. The shared request queue is AT-LEAST-once: an
# advisory timeout is delivered without consuming the callback, and the
# stalled request's real response can then fire it a second time
# (processor.py peek_expired_callback). Each batch gets a fresh sequence
# number; _finish ignores anything that is not the current batch, so a
# duplicate delivery cannot double-release the FIFO.
_batch_seq = 0


# =============================================================================
# Payload parsing
# =============================================================================

def parse_strokes_payload(payload: str) -> dict:
    """Validate the C++ ink payload and return it as plain Python data.

    Shape (frozen contract with the ink overlay)::

        {"w": <region_width>, "h": <region_height>,
         "strokes": [[[x, y, p], ...], ...]}

    ``x``/``y`` are region-local pixels with y **up**; ``p`` is pressure 0..1
    (1.0 for a mouse). An empty stroke list is legal — a tap that drew
    nothing is not an error, just nothing to convert.

    Raises:
        ValueError: on anything that is not a well-formed payload within the
            caps. C++ enforces the same limits while capturing, so this only
            fires on a skewed build — but it fires before any pixels or
            credits are spent.
    """
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError("Empty stroke payload")
    # Checked on the raw string: rejecting a pathological blob costs a
    # length compare instead of a full parse.
    if len(payload) > SCRIBBLE_COMMIT_MAXLEN:
        raise ValueError(
            f"Stroke payload too large "
            f"({len(payload)} > {SCRIBBLE_COMMIT_MAXLEN} bytes)"
        )

    try:
        data = json.loads(payload)
    except ValueError as e:
        raise ValueError(f"Malformed stroke payload: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Stroke payload is not an object")

    raw_strokes = data.get("strokes")
    if not isinstance(raw_strokes, (list, tuple)):
        raise ValueError("Stroke payload has no strokes list")
    if len(raw_strokes) > SCRIBBLE_MAX_STROKES:
        raise ValueError(
            f"Too many strokes ({len(raw_strokes)} > {SCRIBBLE_MAX_STROKES})"
        )

    strokes = []
    total_points = 0
    for raw_stroke in raw_strokes:
        if not isinstance(raw_stroke, (list, tuple)):
            raise ValueError("Stroke is not a list of points")
        points = [_parse_point(raw_point) for raw_point in raw_stroke]
        if not points:
            continue
        total_points += len(points)
        if total_points > SCRIBBLE_MAX_POINTS:
            raise ValueError(
                f"Too many ink points (> {SCRIBBLE_MAX_POINTS})"
            )
        strokes.append(points)

    return {
        "w": _positive_int(data.get("w"), "w"),
        "h": _positive_int(data.get("h"), "h"),
        "strokes": strokes,
    }


def _parse_point(raw_point) -> Tuple[float, float, float]:
    """One ``[x, y, p]`` point; pressure defaults to 1.0 and clamps to 0..1."""
    if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
        raise ValueError("Ink point is not [x, y, p]")
    try:
        x = float(raw_point[0])
        y = float(raw_point[1])
        pressure = float(raw_point[2]) if len(raw_point) > 2 else 1.0
    except (TypeError, ValueError) as e:
        raise ValueError(f"Ink point is not numeric: {e}") from e
    return x, y, min(1.0, max(0.0, pressure))


def _positive_int(value, field: str) -> int:
    """Region dimension — must be a real, positive pixel count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Stroke payload field {field!r} is not a number")
    if value <= 0:
        raise ValueError(f"Stroke payload field {field!r} must be positive")
    return int(value)


# =============================================================================
# Commit / submit queue
# =============================================================================

def handle_commit(scene, payload: str) -> bool:
    """Entry point for ``mixie_chat.ink_commit``.

    Returns True when a request was started or queued, False when there was
    nothing to convert.

    Raises:
        ValueError: the payload is malformed (the operator reports it).
    """
    data = parse_strokes_payload(payload)
    if not data["strokes"]:
        return False
    submit_strokes(scene, data)
    return True


def submit_strokes(scene, payload: dict) -> None:
    """Rasterize *payload* and POST it, queueing behind any in-flight batch."""
    image_bytes = _rasterize(payload)
    if _in_flight:
        _pending.append((scene, image_bytes))
        _set_busy()
        return
    _start(scene, image_bytes)


def is_busy() -> bool:
    """True while a batch is in flight or waiting."""
    return bool(_in_flight or _pending)


def flush_pending_ink() -> None:
    """Ask the C++ overlay to convert any un-committed strokes NOW.

    Every Python path that clears ``mixie_chat_ink_visible`` (the header
    toggle, the rules/history toggles enforcing overlay exclusivity) must
    call this FIRST: the C++ draw-side closing edge cannot dispatch
    operators, so without the flush a toggle-close silently drops whatever
    the user just wrote. C++-side closes (Esc, close X) flush on their own.
    """
    try:
        import bpy

        if hasattr(bpy.types, "MIXIE_CHAT_OT_ink_flush"):
            bpy.ops.mixie_chat.ink_flush()
    except Exception:
        logger.debug("[Scribble] ink flush failed", exc_info=True)


def reset_state() -> None:
    """Drop all queued work (file load, unregister, tests)."""
    global _in_flight, _batch_seq
    _in_flight = False
    _batch_seq += 1  # orphan any in-flight delivery
    _pending.clear()


def _start(scene, image_bytes: bytes) -> None:
    """POST one batch and wire its completion back onto this queue."""
    global _in_flight, _batch_seq
    _in_flight = True
    _batch_seq += 1
    seq = _batch_seq
    _set_busy()

    def _on_success(response):
        _finish(seq, scene, _recognized_text(response), None)

    def _on_error(error):
        _finish(seq, scene, "", error)

    try:
        _post(image_bytes, _hint_for(scene), _on_success, _on_error)
    except Exception as e:
        # A failure to even dispatch must still release the queue, or every
        # later batch waits on a request that was never made.
        logger.error("[Scribble] failed to submit handwriting: %s", e)
        _finish(seq, scene, "", e)


def _finish(seq: int, scene, text: str, error: Optional[Exception]) -> None:
    """Deliver one result on the main thread, then start the next batch."""
    global _in_flight
    if not _in_flight or seq != _batch_seq:
        # Stale duplicate from the at-least-once queue (advisory timeout
        # followed by the real response) — the batch was already settled.
        logger.debug("[Scribble] ignoring stale delivery for batch %s", seq)
        return
    _in_flight = False
    try:
        if error is not None:
            _report_error(scene, error)
        elif text:
            _append_recognized(scene, text)
        else:
            # Illegible or blank: silently nothing, the way lifting the pen
            # off an unreadable scrawl does on iPadOS.
            logger.debug("[Scribble] nothing legible in this batch")
    except Exception:
        logger.error("[Scribble] failed to deliver recognized text",
                     exc_info=True)
    finally:
        if _pending:
            next_scene, next_bytes = _pending.pop(0)
            _start(next_scene, next_bytes)
        else:
            # Clears the overlay's "Converting…" indicator; C++ reads the
            # flag per draw, so the redraw inside _set_busy is what makes
            # it disappear without the user moving the mouse.
            _set_busy()


# =============================================================================
# Seams: everything below is where this module touches the outside world
# =============================================================================

def _rasterize(payload: dict) -> bytes:
    """Render the strokes to PNG bytes (separate seam so tests can skip PIL)."""
    from .scribble_raster import rasterize_strokes

    return rasterize_strokes(payload)


def _post(image_bytes: bytes, hint: str, on_success, on_error) -> None:
    """Send one batch. Callbacks are delivered on Blender's main thread by
    the shared async request queue."""
    from mixar.modules.common.api.services import get_handwriting_service

    get_handwriting_service().recognize_async(
        image_bytes,
        filename="scribble.png",
        hint=hint,
        on_success=on_success,
        on_error=on_error,
    )


def _set_busy() -> None:
    """Publish the queue state for the overlay and repaint the chat."""
    busy = is_busy()
    try:
        import bpy

        window_manager = bpy.context.window_manager
        if getattr(window_manager, "mixie_chat_ink_busy", None) != busy:
            window_manager.mixie_chat_ink_busy = busy
    except Exception:
        logger.debug("[Scribble] could not publish busy flag", exc_info=True)
    _redraw()


def _redraw() -> None:
    from .ui_utils import redraw_chat_areas

    redraw_chat_areas()


# =============================================================================
# Result handling
# =============================================================================

def _recognized_text(response) -> str:
    """Pull ``data.text`` out of the standard response envelope."""
    envelope = getattr(response, "data", None)
    if not isinstance(envelope, dict):
        return ""
    data = envelope.get("data", envelope)
    if not isinstance(data, dict):
        return ""
    text = data.get("text")
    if not isinstance(text, str):
        return ""
    # \x1F is in-band protocol on mixie_chat_input: a trailing one is how the
    # C++ Enter hook asks on_chat_input_changed to submit. Recognized text is
    # network-sourced, so it must never be able to send the message the user
    # is still in the middle of writing. Newlines are kept — deliberate line
    # breaks in the handwriting are transcribed as line breaks.
    return text.replace("\x1F", "").strip()


def _release_composer() -> None:
    """Exit any active composer text-edit before appending.

    An active text-edit holds a private buffer that is written back over the
    property on the user's next keystroke, silently erasing a transcription
    that landed mid-edit. Exiting costs nothing: TEXTEDIT_UPDATE applies
    every typed character to the property as it is typed.
    """
    try:
        import bpy

        if hasattr(bpy.types, "MIXIE_CHAT_OT_ink_release_composer"):
            bpy.ops.mixie_chat.ink_release_composer()
    except Exception:
        logger.debug("[Scribble] could not release composer focus",
                     exc_info=True)


def _append_recognized(scene, text: str) -> None:
    """Append *text* to the composer with smart spacing, then repaint.

    Writing ``mixie_chat_input`` fires ``on_chat_input_changed``; that only
    acts on the ``\\x1F`` Enter marker, which recognized text never carries,
    so nothing auto-submits.
    """
    _release_composer()
    current = getattr(scene, "mixie_chat_input", "")
    if not isinstance(current, str):
        current = ""
    if current and not current[-1].isspace():
        text = " " + text
    scene.mixie_chat_input = (current + text)[:CHAT_INPUT_MAXLEN]
    _redraw()


def _hint_for(scene) -> str:
    """Tail of the composer, sent as advisory recognition context."""
    current = getattr(scene, "mixie_chat_input", "")
    if not isinstance(current, str):
        return ""
    return current[-SCRIBBLE_HINT_TAIL_CHARS:].strip()


def _report_error(scene, error) -> None:
    """Surface a failure as an agent bubble — the chat's own error surface,
    visible in the docked chat and the Agent Bubble alike."""
    message = _error_message(error)
    logger.error("[Scribble] recognition failed: %s", error)
    try:
        from .message_helpers import add_agent_message

        add_agent_message(scene, message)
    except Exception:
        logger.debug("[Scribble] could not add error message", exc_info=True)


def _error_message(error) -> str:
    """User-facing message for a failed recognition call.

    Reuses the job queue's shared classifier (402 out of credits, 401 signed
    out, ...); a 502 means the recognition engine itself failed and the call
    is free to retry.

    A backend 502 usually does NOT arrive with status_code=502: the shared
    HTTPClient session retries 5xx transparently and then raises
    requests.exceptions.RetryError ("too many 502 error responses"), which
    reaches this callback untyped — detect it by name/message so the vendor
    outage still reads as "try writing it again" instead of a raw
    max-retries string.
    """
    from mixar.modules.common.job_queue.core.error_helpers import (
        classify_error, sanitize_message,
    )

    engine_failed = (
        getattr(error, "status_code", None) == 502
        or type(error).__name__ == "RetryError"
        or "too many 502" in str(error)
    )
    if engine_failed:
        return "Couldn't read that handwriting — please try writing it again"
    return classify_error(error) or sanitize_message(
        str(error), "Handwriting conversion failed"
    )
