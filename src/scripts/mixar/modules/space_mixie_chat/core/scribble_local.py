# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble's instant path — on-device handwriting recognition.

The backend transcriber (a vision LLM) answers in 1–6 s per batch; on macOS
the platform recogniser reads the same PNG in a few hundred milliseconds,
offline. ``core/scribble.py`` tries this first for every batch and falls back
to the backend when there is no local recogniser, when it fails, or when it
is not confident enough (``SCRIBBLE_LOCAL_MIN_CONFIDENCE``) — so the user
gets instant text for legible writing and the stronger model for the rest.

The queue itself is ``bpy``-free (``LocalRecognitionQueue``): submission and
polling are injected, which is what lets the ordering, timeout and fallback
rules run under the standalone test suite. The thin glue below reaches the
recogniser through two C++ operators (``mixie_chat_ink_local.cc``):

* ``mixie_chat.ink_recognize_local(job, image_path)`` — starts one batch;
  its ``poll`` is the platform capability, so ``available()`` is simply that
  poll and Python keeps no platform table;
* ``mixie_chat.ink_local_poll`` — pops one finished result into the
  ``mixie_chat_ink_local_*`` WindowManager properties (results are produced
  on a system queue and must only cross into Blender from the main thread).

This path takes the STROKES, not the app's raster. Its page is framed
differently (a text line, not a 1280 px longest edge), so going through the
raster meant rendering a page, decoding it, thresholding it, cropping it and
resampling it down — and rendering that page at all is wasted whenever the
local recogniser answers, which is the point of having one. ``core/scribble``
therefore keeps the parsed payload and rasterizes for the backend only when
the backend is actually used.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    SCRIBBLE_LOCAL_LINE_HEIGHT_PX,
    SCRIBBLE_LOCAL_MAX_WIDTH_PX,
    SCRIBBLE_LOCAL_MIN_CONFIDENCE,
    SCRIBBLE_LOCAL_PAGE_PAD_X,
    SCRIBBLE_LOCAL_PAGE_PAD_Y,
    SCRIBBLE_LOCAL_POLL_S,
    SCRIBBLE_LOCAL_TIMEOUT_S,
)
from .scribble_raster import line_geometry, render

logger = get_logger(__name__)

# on_done(text, confidence, ok)
ResultCallback = Callable[[str, float, bool], None]
# (job, text, confidence, ok)
PoppedResult = Tuple[int, str, float, bool]


def vision_page(payload: dict) -> bytes:
    """The recogniser's copy of one batch, drawn from the stroke VECTORS.

    Framed as a text line rather than as the app's 1280 px raster: Vision
    refuses a one- or two-glyph batch drawn 300+ px tall (line art, not
    text) and read the same ink perfectly once it was a
    ``SCRIBBLE_LOCAL_LINE_HEIGHT_PX`` line with page margins around it,
    while two- and three-line blocks at that total height still read line
    by line.

    Drawn straight from the strokes, not resampled from the raster the
    backend gets. That raster exists to be read by a vision model at a
    different size entirely, so going through it meant rendering the ink
    once, decoding it, thresholding it, cropping it and resampling it down
    — paying for a page that is then thrown away whenever the local
    recogniser answers, which on this path is the common case. The curve is
    the same curve either way; only this one has not been through a
    lossy round trip to get here.
    """
    geometry = line_geometry(
        payload,
        line_height=SCRIBBLE_LOCAL_LINE_HEIGHT_PX,
        max_width=SCRIBBLE_LOCAL_MAX_WIDTH_PX,
        pad_x=SCRIBBLE_LOCAL_PAGE_PAD_X,
        pad_y=SCRIBBLE_LOCAL_PAGE_PAD_Y,
    )
    return render(payload, geometry)


def accept(text: str, confidence: float) -> bool:
    """Whether a local reading is good enough to skip the backend.

    Empty text is never accepted: a blank or illegible batch is exactly the
    case the stronger model should see, since "nothing" is also what a local
    recogniser says about cursive it cannot read.
    """
    return bool((text or "").strip()) and confidence >= SCRIBBLE_LOCAL_MIN_CONFIDENCE


class LocalRecognitionQueue:
    """Outstanding local batches, keyed by job id.

    ``submit_fn(job, image_bytes) -> bool`` hands a batch to the recogniser;
    ``pop_fn() -> PoppedResult | None`` collects one finished result. A batch
    that never comes back is failed at its deadline so the caller's fallback
    still runs — a recogniser that hangs must not hang the composer.
    """

    def __init__(
        self,
        submit_fn: Callable[[int, bytes], bool],
        pop_fn: Callable[[], Optional[PoppedResult]],
        now_fn: Callable[[], float] = time.monotonic,
        timeout_s: float = SCRIBBLE_LOCAL_TIMEOUT_S,
    ):
        self._submit = submit_fn
        self._pop = pop_fn
        self._now = now_fn
        self._timeout = timeout_s
        self._jobs: Dict[int, Tuple[ResultCallback, float]] = {}
        self._next_job = 1

    @property
    def pending(self) -> int:
        return len(self._jobs)

    def submit(self, image_bytes: bytes, on_done: ResultCallback) -> bool:
        """Start one batch. False when the recogniser refused it (the caller
        then goes straight to the backend)."""
        job = self._next_job
        self._next_job += 1
        try:
            started = bool(self._submit(job, image_bytes))
        except Exception:  # noqa: BLE001 — a refusal, not an outage
            logger.debug("[Scribble] local recogniser refused a batch", exc_info=True)
            started = False
        if not started:
            return False
        self._jobs[job] = (on_done, self._now() + self._timeout)
        return True

    def pump(self) -> bool:
        """Deliver everything that landed, fail what timed out. Returns True
        while batches are still outstanding."""
        while True:
            try:
                popped = self._pop()
            except Exception:  # noqa: BLE001
                logger.debug("[Scribble] local result poll failed", exc_info=True)
                popped = None
            if popped is None:
                break
            job, text, confidence, ok = popped
            entry = self._jobs.pop(job, None)
            if entry is None:
                # Timed out already (and handed to the backend), or a job of a
                # previous session — nothing is waiting for it.
                continue
            self._call(entry[0], text, confidence, ok)

        now = self._now()
        for job, (on_done, deadline) in list(self._jobs.items()):
            if now >= deadline:
                del self._jobs[job]
                self._call(on_done, "", 0.0, False)
        return bool(self._jobs)

    def reset(self) -> None:
        """Fail every outstanding batch (a session reset)."""
        jobs = list(self._jobs.items())
        self._jobs.clear()
        for _job, (on_done, _deadline) in jobs:
            self._call(on_done, "", 0.0, False)

    @staticmethod
    def _call(on_done: ResultCallback, text: str, confidence: float, ok: bool) -> None:
        try:
            on_done(text, confidence, ok)
        except Exception:  # noqa: BLE001 — one batch's handler must not stall the queue
            logger.error("[Scribble] local result handler failed", exc_info=True)


# =============================================================================
# Blender glue
# =============================================================================

_queue: Optional[LocalRecognitionQueue] = None
_paths: Dict[int, str] = {}


def available() -> bool:
    """True when this build and platform have an on-device recogniser."""
    try:
        import bpy

        op = getattr(getattr(bpy.ops, "mixie_chat", None), "ink_recognize_local", None)
        return op is not None and bool(op.poll())
    except Exception:  # noqa: BLE001
        return False


def try_start(payload: dict, on_done: ResultCallback) -> bool:
    """Try the instant path for one batch. False when it cannot even start —
    the caller keeps the batch and posts it to the backend."""
    if not available():
        return False
    try:
        page = vision_page(payload)
    except Exception:  # noqa: BLE001 — the backend path is always there
        logger.debug("[Scribble] could not frame the ink for the local recogniser",
                     exc_info=True)
        return False
    queue = _ensure_queue()
    if not queue.submit(page, on_done):
        return False
    _ensure_timer()
    return True


def reset() -> None:
    if _queue is not None:
        _queue.reset()
    for path in list(_paths.values()):
        _remove_quietly(path)
    _paths.clear()


def _ensure_queue() -> LocalRecognitionQueue:
    global _queue
    if _queue is None:
        _queue = LocalRecognitionQueue(_submit_via_operator, _pop_via_operator)
    return _queue


def _submit_via_operator(job: int, image_bytes: bytes) -> bool:
    import bpy

    directory = bpy.app.tempdir or ""
    path = os.path.join(directory, f"mixar_scribble_{job}.png")
    with open(path, "wb") as handle:
        handle.write(image_bytes)
    _paths[job] = path
    try:
        result = bpy.ops.mixie_chat.ink_recognize_local(job=job, image_path=path)
    except Exception:
        _paths.pop(job, None)
        _remove_quietly(path)
        raise
    if "FINISHED" not in result:
        _paths.pop(job, None)
        _remove_quietly(path)
        return False
    return True


def _pop_via_operator() -> Optional[PoppedResult]:
    import bpy

    op = getattr(getattr(bpy.ops, "mixie_chat", None), "ink_local_poll", None)
    if op is None or not op.poll():
        return None
    if "FINISHED" not in op():
        return None
    wm = bpy.context.window_manager
    job = int(getattr(wm, "mixie_chat_ink_local_job", 0))
    text = str(getattr(wm, "mixie_chat_ink_local_text", "") or "")
    confidence = float(getattr(wm, "mixie_chat_ink_local_confidence", 0.0))
    ok = bool(getattr(wm, "mixie_chat_ink_local_ok", False))
    _remove_quietly(_paths.pop(job, ""))
    return job, text, confidence, ok


def _ensure_timer() -> None:
    import bpy

    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=SCRIBBLE_LOCAL_POLL_S)


def _tick():
    queue = _queue
    if queue is None:
        return None
    try:
        still_pending = queue.pump()
    except Exception:  # noqa: BLE001 — a timer callback must not raise
        logger.error("[Scribble] local recognition pump failed", exc_info=True)
        still_pending = queue.pending > 0
    return SCRIBBLE_LOCAL_POLL_S if still_pending else None


def _remove_quietly(path: str) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass
