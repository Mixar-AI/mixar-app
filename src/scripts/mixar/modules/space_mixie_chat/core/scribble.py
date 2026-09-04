# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Scribble — handwriting strokes to text in the chat composer.

The C++ ink overlay captures the strokes and, ~``SCRIBBLE_IDLE_COMMIT_MS``
after the pen lifts, dispatches ``mixie_chat.ink_commit`` with them as JSON
and clears its canvas. Everything from that point is here: validate the
payload, rasterize it (``scribble_raster``), POST it to the handwriting
endpoint, and append the transcription to ``scene.mixie_chat_input``.

**Pipelined on the wire, delivered in order.** A user writing continuously
produces a new batch every pause, and each round trip is about a second at
the model's floor. Waiting for one batch to land before posting the next
would make the composer lag further behind the pen with every pause, so up
to ``SCRIBBLE_MAX_IN_FLIGHT`` batches travel at once — but their text enters
the composer strictly in the order it was written: a batch that lands early
waits for the ones before it. Later batches queue behind the in-flight ones.

The hint is resolved when a batch is POSTED, not when it is queued, so a
batch that waited for a slot continues the sentence its predecessors already
appended. A batch that starts while another is still in flight sees the
composer as it is at that moment — the hint is advisory, and the recognizer
is told the image is authoritative.

``bpy`` is reached only through late imports so the standalone test suite can
exercise the parsing, spacing and queue logic outside Blender.
"""

import json
from typing import Dict, List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    CHAT_INPUT_MAXLEN,
    SCRIBBLE_COMMIT_MAXLEN,
    SCRIBBLE_HINT_TAIL_CHARS,
    SCRIBBLE_MAX_IN_FLIGHT,
    SCRIBBLE_MAX_POINTS,
    SCRIBBLE_MAX_STROKES,
)

logger = get_logger(__name__)

# Batches on the wire, by sequence number. The value is the scene the text
# lands in. Membership is also the delivery-dedup test: the shared request
# queue is AT-LEAST-once (an advisory timeout is delivered without consuming
# the callback, and the stalled request's real response can then fire it a
# second time — processor.py peek_expired_callback), and a batch that is no
# longer here has already been settled.
_in_flight: Dict[int, object] = {}

# Batches waiting for a slot, oldest first: (seq, scene, png_bytes). The
# strokes are rasterized when they are handed over, so a malformed batch
# fails at the operator rather than seconds later when its turn comes up.
_pending: List[Tuple[int, object, bytes]] = []

# Batches that have landed but whose predecessors have not: seq -> (scene,
# text, error). Released into the composer in sequence order.
_landed: Dict[int, Tuple[object, str, Optional[Exception]]] = {}

# Sequence numbers: the next to hand out, and the next allowed into the
# composer. Everything between them is somewhere in the three stores above.
_next_seq = 0
_deliver_seq = 0

# Re-entrancy guard for the pump: a synchronous failure inside _start lands
# in _finish, which pumps again while the outer pump's loop is still running.
_pumping = False


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
    """Rasterize *payload* and put it on the wire, or behind the batches
    already there when every slot is taken."""
    global _next_seq
    image_bytes = _rasterize(payload)
    seq = _next_seq
    _next_seq += 1
    _pending.append((seq, scene, image_bytes))
    _pump()


def is_busy() -> bool:
    """True while any batch is on the wire, waiting for a slot, or landed
    but still waiting for a predecessor."""
    return bool(_in_flight or _pending or _landed)


def defer_until_idle(callback, timeout_s: float = 15.0, poll_s: float = 0.1) -> bool:
    """Run *callback* once no recognition is in flight. True if it was deferred.

    False means nothing is pending and the caller should simply proceed.
    Used by the send path: handwriting still being converted belongs to the
    message about to go out, and a prompt written entirely by hand is EMPTY
    until its last batch lands. The timeout bounds a stalled request — a
    message that waits forever on a transcription that will never arrive is
    worse than one sent without its final handwritten words.
    """
    if not is_busy():
        return False

    import time

    import bpy

    deadline = time.monotonic() + timeout_s

    def _tick():
        if is_busy() and time.monotonic() < deadline:
            return poll_s
        try:
            callback()
        except Exception:  # noqa: BLE001 — a timer callback must not raise
            logger.error("[Scribble] deferred callback failed", exc_info=True)
        return None

    bpy.app.timers.register(_tick, first_interval=poll_s)
    return True


def _c_operator_available(name: str) -> bool:
    """Whether the C++ chat editor registered ``mixie_chat.<name>``.

    ``hasattr(bpy.ops.mixie_chat, name)`` is useless (bpy.ops fabricates a
    wrapper for any name and only fails on call), and ``bpy.types`` lists
    only Python-registered operator classes — so the C ink operators have to
    be looked up in the submodule's real listing.
    """
    try:
        import bpy

        return name in dir(bpy.ops.mixie_chat)
    except Exception:
        return False


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

        # C-registered operators (WM_operatortype_append) are NOT exposed on
        # bpy.types — only Python-registered classes are — so a bpy.types gate
        # here was always False in the built app and the flush never ran. The
        # operator submodule's dir() lists what actually exists.
        if _c_operator_available("ink_flush"):
            bpy.ops.mixie_chat.ink_flush()
    except Exception:
        logger.debug("[Scribble] ink flush failed", exc_info=True)


def reset_state() -> None:
    """Drop all queued work (file load, unregister, tests).

    Anything still on the wire is orphaned: its delivery finds no in-flight
    entry and is ignored, so a batch written into the OLD file can never
    append its text into the new one.
    """
    global _deliver_seq
    _in_flight.clear()
    _pending.clear()
    _landed.clear()
    _deliver_seq = _next_seq


def _pump() -> None:
    """Move waiting batches onto the wire while there are free slots."""
    global _pumping
    if _pumping:
        return
    _pumping = True
    try:
        while _pending and len(_in_flight) < SCRIBBLE_MAX_IN_FLIGHT:
            seq, scene, image_bytes = _pending.pop(0)
            _start(seq, scene, image_bytes)
    finally:
        _pumping = False
    _set_busy()


def _start(seq: int, scene, image_bytes: bytes) -> None:
    """POST one batch and wire its completion back onto this queue."""
    _in_flight[seq] = scene

    def _on_success(response):
        _finish(seq, _recognized_text(response), None)

    def _on_error(error):
        _finish(seq, "", error)

    try:
        _post(image_bytes, _hint_for(scene), _on_success, _on_error)
    except Exception as e:
        # A failure to even dispatch must still release the slot, or every
        # later batch waits on a request that was never made.
        logger.error("[Scribble] failed to submit handwriting: %s", e)
        _finish(seq, "", e)


def _finish(seq: int, text: str, error: Optional[Exception]) -> None:
    """One batch landed: hold it until its predecessors have, then release
    everything that is now deliverable, and refill the wire."""
    scene = _in_flight.pop(seq, None)
    if scene is None:
        # Stale duplicate from the at-least-once queue (advisory timeout
        # followed by the real response), or a batch orphaned by a reset.
        logger.debug("[Scribble] ignoring stale delivery for batch %s", seq)
        return
    _landed[seq] = (scene, text, error)
    _deliver()
    _pump()


def _deliver() -> None:
    """Release landed batches into the composer, strictly in written order."""
    global _deliver_seq
    while _deliver_seq in _landed:
        scene, text, error = _landed.pop(_deliver_seq)
        _deliver_seq += 1
        try:
            if error is not None:
                _report_error(scene, error)
            elif text:
                _append_recognized(scene, text)
            else:
                # Illegible or blank: silently nothing, the way lifting the
                # pen off an unreadable scrawl does on iPadOS.
                logger.debug("[Scribble] nothing legible in this batch")
        except Exception:
            logger.error("[Scribble] failed to deliver recognized text",
                         exc_info=True)


# =============================================================================
# Canvas visibility — shared with the C++ overlay through the WM flags
# =============================================================================

def canvas_available(wm) -> bool:
    """Whether the handwriting canvas exists in this build.

    The flag is registered by ``ui/properties/ink_props.py``; the C++ overlay
    reads it per draw. Without the flag there is nothing to open.
    """
    return wm is not None and hasattr(wm, "mixie_chat_ink_visible")


def is_canvas_open(wm) -> bool:
    return bool(getattr(wm, "mixie_chat_ink_visible", False))


def open_canvas(wm) -> bool:
    """Raise the canvas over every chat surface. True when it is up."""
    if not canvas_available(wm):
        return False
    # Scribble, project rules and past chats are all modal over the same
    # chat surface — only one may be open at a time.
    if getattr(wm, "mixie_chat_rules_visible", False):
        wm.mixie_chat_rules_visible = False
    if getattr(wm, "mixie_chat_history_visible", False):
        wm.mixie_chat_history_visible = False
    if not wm.mixie_chat_ink_visible:
        wm.mixie_chat_ink_visible = True
    _redraw()
    return True


def close_canvas(wm) -> None:
    """Lower the canvas, converting whatever is still on it FIRST.

    The C++ draw-side closing edge cannot dispatch operators, so a Python
    close that skipped the flush would silently drop the user's last words.
    """
    if not is_canvas_open(wm):
        return
    flush_pending_ink()
    wm.mixie_chat_ink_visible = False
    _redraw()


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

        if _c_operator_available("ink_release_composer"):
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
    # A 404 here is the ROUTE missing — a backend without the handwriting
    # half (seen on uat7 during the first in-app pass) — not a missing
    # resource of the user's. The shared classifier's "Resource not found"
    # reads as if something they wrote was lost.
    if getattr(error, "status_code", None) == 404 or "Not Found" in str(error):
        return ("Handwriting recognition isn't available on this server yet — "
                "type the message instead")
    return classify_error(error) or sanitize_message(
        str(error), "Handwriting conversion failed"
    )
