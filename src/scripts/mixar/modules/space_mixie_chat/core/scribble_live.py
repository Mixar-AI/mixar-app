# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Live transcription — the text appears while you write.

Recognition used to start only after the pen had rested for
``SCRIBBLE_IDLE_COMMIT_MS``, and every request sits at the model's ~1 s
floor, so a word showed up about two seconds after its last stroke. Now
every pen-up sends the ink written so far as a PREVIEW, its text is shown in
the composer the moment it lands, and the pause that ends the batch usually
finds the answer already there: the final commit either matches a preview
that landed (instant), adopts the preview still on the wire, or — only when
strokes were added after the last preview — posts afresh.

Three ideas keep this cheap and honest:

* **One preview on the wire, ever.** A pen-up while one is out replaces the
  batch's pending preview rather than queueing behind it, so only the newest
  ink is ever sent and the request rate is bounded by the round trip, never
  by how fast the pen lifts.
* **Ink is keyed by its serialized bytes.** "The same ink" is an exact match
  between what a pen-up sent and what the pause commits — no geometry
  comparison, no drift.
* **The composer is a document of segments.** Each batch owns one segment,
  provisional until its final text lands, and the composer is re-rendered
  from a frozen base plus the segments — so a final that differs from its
  preview REPLACES the preview instead of landing after it. If the user
  edits the composer mid-flight, whatever is on screen is frozen into the
  base and later results append after it: nothing is duplicated or deleted
  behind them.

``bpy`` is reached only through ``scribble``'s late-bound seams, so the
standalone suite drives all of this with a duck-typed scene.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import CHAT_INPUT_MAXLEN, SCRIBBLE_HINT_TAIL_CHARS

logger = get_logger(__name__)

PLAN_CACHED = "cached"
PLAN_ADOPT = "adopt"
PLAN_POST = "post"


class Segment:
    """One batch's text in the composer document."""

    __slots__ = ("batch_id", "text", "shown", "final", "frozen")

    def __init__(self, batch_id: int):
        self.batch_id = batch_id
        self.text = ""
        # What was on screen at the last render — the part of this segment
        # a user edit would have folded into the base.
        self.shown = ""
        self.final = False
        # The user edited the composer while this was on screen: its text
        # now lives in the base and later results must not touch it.
        self.frozen = False


class Batch:
    """The ink between two final commits, and its previews."""

    __slots__ = ("id", "scene", "seq", "results", "inflight", "pending",
                 "adopt_key", "adopter", "segment")

    def __init__(self, batch_id: int, scene):
        self.id = batch_id
        self.scene = scene
        self.seq: Optional[int] = None
        self.results: Dict[str, str] = {}
        self.inflight: Optional[str] = None
        self.pending: Optional[Tuple[str, bytes]] = None
        self.adopt_key: Optional[str] = None
        self.adopter: Optional[Callable[[str, Optional[Exception]], None]] = None
        self.segment: Optional[Segment] = None


_open: Optional[Batch] = None
_closed: Dict[int, Batch] = {}       # by seq, until finalized
_inflight_batches: List[Batch] = []  # any batch with a preview on the wire
_segments: List[Segment] = []
_scene = None
_base = ""
_rendered: Optional[str] = None
_next_batch = 0


# =============================================================================
# Keys and text
# =============================================================================

def payload_key(payload_text: str) -> str:
    """Identity of a batch's ink: the serialized bytes the canvas sent."""
    return hashlib.sha1(payload_text.encode("utf-8")).hexdigest()


def join_text(current: str, piece: str) -> str:
    """Append *piece* with the composer's smart spacing."""
    if not piece:
        return current
    if current and not current[-1].isspace():
        return current + " " + piece
    return current + piece


# =============================================================================
# Previews (pen-up)
# =============================================================================

def preview(scene, data: dict, key: str) -> bool:
    """A pen-up handed over the batch's ink so far. True when it is (or is
    about to be) on the wire, or its text is already on screen."""
    global _open
    if not data.get("strokes"):
        discard_open()
        return False
    if _open is None or _open.scene is not scene:
        _open = _new_batch(scene)
    batch = _open
    if key in batch.results:
        _show(batch, key)
        return True
    if batch.inflight == key:
        return True
    image = _rasterize(data)
    if batch.inflight is not None:
        # Only the newest ink is worth sending once the wire frees up.
        batch.pending = (key, image)
        return True
    _post_preview(batch, key, image)
    return True


def _post_preview(batch: Batch, key: str, image: bytes) -> None:
    batch.inflight = key
    if batch not in _inflight_batches:
        _inflight_batches.append(batch)

    def _on_success(response):
        _landed(batch, key, _text_of(response), None)

    def _on_error(error):
        _landed(batch, key, "", error)

    try:
        _post(image, hint_text(batch.scene, exclude=batch), _on_success, _on_error)
    except Exception as exc:  # noqa: BLE001 — a preview is best-effort
        logger.debug("[Scribble] preview dispatch failed: %s", exc)
        _landed(batch, key, "", exc)


def _landed(batch: Batch, key: str, text: str, error) -> None:
    """A preview came back. Show it, hand it to a final that adopted it, and
    send the newest pending ink."""
    if batch.inflight != key:
        return  # superseded, discarded, or an at-least-once duplicate
    batch.inflight = None
    if batch in _inflight_batches:
        _inflight_batches.remove(batch)
    if error is None:
        batch.results[key] = text
    else:
        logger.debug("[Scribble] preview failed: %s", error)

    if batch.adopter is not None and batch.adopt_key == key:
        adopter, batch.adopter = batch.adopter, None
        adopter(text, error)
        return

    if error is None and (batch.segment is None or not batch.segment.final):
        _show(batch, key)

    if batch is _open and batch.pending is not None:
        pending_key, image = batch.pending
        batch.pending = None
        if pending_key not in batch.results:
            _post_preview(batch, pending_key, image)
    _notify()


def _show(batch: Batch, key: str) -> None:
    """Put a landed preview on screen. An empty reading keeps the previous
    text rather than blanking the word mid-write; the final settles it."""
    text = batch.results.get(key, "")
    segment = batch.segment
    if segment is None:
        if not text:
            return
        segment = _new_segment(batch)
    if text or segment.text == "":
        segment.text = text
    _render()


# =============================================================================
# Finals (the pause, Enter, close)
# =============================================================================

def close_batch(scene, key: str, seq: int) -> Tuple[Batch, str]:
    """The pause committed *key*. Returns the batch and how to settle it:
    ``cached`` (its text landed already), ``adopt`` (its preview is on the
    wire), or ``post`` (strokes were added after the last preview)."""
    global _open
    batch = _open if (_open is not None and _open.scene is scene) else None
    _open = None
    if batch is None:
        batch = _new_batch(scene)
    batch.seq = seq
    batch.pending = None
    _closed[seq] = batch
    if key in batch.results:
        return batch, PLAN_CACHED
    if batch.inflight == key:
        batch.adopt_key = key
        return batch, PLAN_ADOPT
    return batch, PLAN_POST


def adopt(batch: Batch, callback: Callable[[str, Optional[Exception]], None]) -> None:
    """Route the in-flight preview's landing into the final's callback."""
    batch.adopter = callback


def batch_for(seq: Optional[int]) -> Optional[Batch]:
    """The closed batch settling under *seq*, if any."""
    return _closed.get(seq) if seq is not None else None


def finalize(seq: int, scene, text: Optional[str]) -> None:
    """The final text for *seq* is in (delivered in written order by the
    caller). None keeps whatever preview is on screen — a failed final must
    not erase a word the user already saw."""
    batch = _closed.pop(seq, None)
    if batch is None:
        batch = _new_batch(scene)
    segment = batch.segment
    if segment is None:
        if not text:
            return _collapse_if_settled()
        segment = _new_segment(batch)
    if text is not None:
        segment.text = text
    segment.final = True
    _render()
    _collapse_if_settled()


def discard_open() -> None:
    """The user cleared the canvas: drop the open batch and its preview."""
    global _open
    batch = _open
    _open = None
    if batch is None:
        return
    batch.inflight = None  # its landing is now ignored
    batch.pending = None
    if batch in _inflight_batches:
        _inflight_batches.remove(batch)
    if batch.segment is not None and batch.segment in _segments and not batch.segment.frozen:
        _segments.remove(batch.segment)
        _render()
    _notify()


# =============================================================================
# The document
# =============================================================================

def _new_batch(scene) -> Batch:
    global _next_batch, _scene, _base, _rendered
    if scene is not _scene:
        # A different scene is a different composer: start a fresh document
        # on whatever it currently holds.
        _segments.clear()
        _scene = scene
        _rendered = None
    _next_batch += 1
    return Batch(_next_batch, scene)


def _new_segment(batch: Batch) -> Segment:
    segment = Segment(batch.id)
    batch.segment = segment
    _segments.append(segment)
    return segment


def _render() -> None:
    """Write base + segments to the composer, freezing on external edits."""
    global _base, _rendered
    scene = _scene
    if scene is None:
        return
    current = getattr(scene, "mixie_chat_input", "")
    if not isinstance(current, str):
        current = ""
    if _rendered is None or current != _rendered:
        # The user typed (or a send cleared the box) since we last wrote:
        # what is on screen is theirs now, and every segment already SHOWN
        # lives inside it. A segment that never reached the screen is still
        # ours to place after it.
        _base = current
        for segment in _segments:
            if segment.shown:
                segment.frozen = True
    text = _base
    for segment in _segments:
        if segment.frozen:
            continue
        text = join_text(text, segment.text)
        segment.shown = segment.text
    text = text[:CHAT_INPUT_MAXLEN]
    if text != current:
        _release_composer()
        scene.mixie_chat_input = text
    _rendered = text
    _redraw()


def _collapse_if_settled() -> None:
    """Once every segment is final, fold them into the base."""
    global _base
    if any(not s.final for s in _segments):
        return
    if _rendered is not None:
        _base = _rendered
    _segments.clear()


def hint_text(scene, exclude: Optional[Batch] = None) -> str:
    """Tail of the text BEFORE *exclude*'s own segment — the recognizer is
    told the hint must not be repeated, so a batch's own preview would make
    it transcribe nothing."""
    if scene is not _scene or _rendered is None:
        current = getattr(scene, "mixie_chat_input", "")
        text = current if isinstance(current, str) else ""
    else:
        text = _base
        for segment in _segments:
            if segment.frozen:
                continue
            if exclude is not None and segment is exclude.segment:
                break
            text = join_text(text, segment.text)
    return text[-SCRIBBLE_HINT_TAIL_CHARS:].strip()


def is_busy() -> bool:
    """A preview is on the wire or waiting for it."""
    if _inflight_batches:
        return True
    return _open is not None and _open.pending is not None


def reset() -> None:
    global _open, _scene, _base, _rendered
    _open = None
    _closed.clear()
    _inflight_batches.clear()
    _segments.clear()
    _scene = None
    _base = ""
    _rendered = None


# =============================================================================
# Seams — everything that reaches Blender or the wire goes through scribble
# =============================================================================

def _rasterize(data: dict) -> bytes:
    from . import scribble

    return scribble._rasterize(data)


def _post(image: bytes, hint: str, on_success, on_error) -> None:
    from . import scribble

    scribble._post(image, hint, on_success, on_error)


def _text_of(response) -> str:
    from . import scribble

    return scribble._recognized_text(response)


def _release_composer() -> None:
    from . import scribble

    scribble._release_composer()


def _redraw() -> None:
    from . import scribble

    scribble._redraw()


def _notify() -> None:
    from . import scribble

    scribble._set_busy()
