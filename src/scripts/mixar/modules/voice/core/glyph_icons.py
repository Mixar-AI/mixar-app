# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rasterized mic glyph as Blender preview icons, for the N-panel.

`core/glyph_raster.py` draws the shapes; this is the `bpy` half that turns them
into something `layout.operator(icon_value=...)` accepts, so the sidebar shows
the SAME mic — and the same animation — as the chat composer, the Agent Bubble
and the moodboard node tile, which paint it on the GPU.

Animation is a frame set per moving state, picked per redraw off the live level
and clock by the drawer. The session already repaints every voice surface at 20
fps while recording (`core/session.py`), so nothing here owns a timer.

**Frames are built lazily, per state.** The whole set is ~150 ms of pure-Python
rasterizing, which is not something to spend at startup for a button most
sessions never press; the idle frame alone is a few milliseconds. The animated
sets are built the first time the state is actually entered — i.e. inside the
press that starts a recording, where the cost lands next to a microphone opening
and is invisible.

Everything degrades to "no custom icon" rather than raising: previews are a
resource that can fail to allocate, and a mic that falls back to a stock glyph
is a cosmetic regression, while an exception in a panel draw blanks the tab.
"""

from __future__ import annotations

from typing import List, Set

import bpy

from mixar.config.logging_config import get_logger

from . import glyph_raster as raster

logger = get_logger(__name__)

#: Rasterized cell size. Blender scales a preview to whatever the row gives it,
#: so this only sets how much detail the cradle arc and the spinner keep; 32 is
#: the size Blender's own generated previews use for buttons.
ICON_SIZE = 32

_previews = None
#: States whose frames are rasterized and ready.
_built: Set[str] = set()
#: States whose build RAISED. Kept apart from `_built` on purpose: a single
#: dict cannot distinguish "not built yet" from "will never build", and a
#: falsy entry read as the former means the draw callback re-runs the whole
#: per-pixel raster on every redraw of a failing state.
_unavailable: Set[str] = set()
#: Latched once the collection cannot be allocated, so a draw callback running
#: every mouse move does not retry a failing allocation on every frame.
_failed = False


def _mark_failed() -> None:
    global _previews, _failed
    _previews = None
    _failed = True


def _frame_name(state: str, index: int) -> str:
    return f"mixar_voice_{state.lower()}_{index}"


def _frames_for(state: str) -> List[tuple]:
    """(name, render kwargs) for every frame of `state`."""
    if state == raster.STATE_RECORDING:
        return [
            (_frame_name(state, i), {"halo": raster.recording_frame_factor(i)})
            for i in range(raster.RECORDING_FRAMES)
        ]
    if state == raster.STATE_TRANSCRIBING:
        return [
            (_frame_name(state, i), {"spin": raster.transcribing_frame_angle(i)})
            for i in range(raster.TRANSCRIBING_FRAMES)
        ]
    return [(_frame_name(state, 0), {})]


def _ensure_collection() -> bool:
    """Allocate the preview collection on first use.

    Lazy rather than registered: creation is a plain allocation (no datablock,
    nothing that a draw callback must not do), so making it lazy means the
    module needs no hand-written `register()` — only the teardown below, which
    genuinely has to run.
    """
    global _previews
    if _previews is not None:
        return True
    if _failed:
        return False
    try:
        # Imported here, not at module scope: `bpy.utils.previews` is a
        # submodule Blender does not pull in for you, and a module-level
        # import would make this file unimportable wherever it is absent —
        # including the standalone test suite, where `bpy` is a stub.
        import bpy.utils.previews  # noqa: PLC0415

        _previews = bpy.utils.previews.new()
    except Exception:
        logger.debug("[Voice] preview collection unavailable", exc_info=True)
        _mark_failed()
        return False
    return True


def _ensure_state(state: str) -> bool:
    """Build `state`'s frames if they are not there yet. False if unavailable."""
    if not _ensure_collection():
        return False
    if state in _built:
        return True
    if state in _unavailable:
        return False
    try:
        for name, kwargs in _frames_for(state):
            if name in _previews:
                continue
            preview = _previews.new(name)
            preview.icon_size = (ICON_SIZE, ICON_SIZE)
            preview.icon_pixels_float = raster.render_button(
                ICON_SIZE, state, **kwargs
            )
    except Exception:
        # A partially built state would animate with gaps; drop the whole thing
        # and let the caller fall back to a stock icon.
        logger.debug("[Voice] glyph frames unavailable for %s", state, exc_info=True)
        _unavailable.add(state)
        return False
    _built.add(state)
    return True


def prewarm(state: str) -> None:
    """Build `state`'s frames NOW, off the draw path.

    `icon_id` is reached from a panel `draw()`, and CLAUDE.md's handler pattern
    forbids heavy work there — a state entered for the first time would
    otherwise rasterize its whole set (up to a dozen frames of pure-Python
    per-pixel work) inside the redraw that first shows it. `VoiceSession` calls
    this from `start()` and `stop()`, which run on the main thread from the
    operator press, so the cost lands next to a microphone opening exactly as
    this module's contract says it does.

    Never raises and never reports: a state that cannot be built is latched in
    `_unavailable`, and the drawer falls back to a stock icon.
    """
    try:
        _ensure_state(state)
    except Exception:  # noqa: BLE001 — a warm-up must not break the press
        logger.debug("[Voice] glyph prewarm failed for %s", state, exc_info=True)


def icon_id(state: str, level: float = 0.0, pulse: float = 0.0) -> int:
    """The icon for `state` at this instant, or 0 when there is none.

    0 is Blender's "no icon" value, so a caller can pass it straight through to
    `icon_value=` and get the same layout with an empty slot — which is what the
    drawer's stock-icon fallback keys on.
    """
    if not _ensure_state(state):
        return 0

    if state == raster.STATE_RECORDING:
        index = raster.recording_frame_index(level, pulse)
    elif state == raster.STATE_TRANSCRIBING:
        index = raster.transcribing_frame_index(pulse)
    else:
        index = 0

    preview = _previews.get(_frame_name(state, index))
    return preview.icon_id if preview is not None else 0


def unregister() -> None:
    """Release the preview collection.

    Blender holds preview collections outside Python's module state, so a
    reload that dropped this module without releasing them would leak the
    images and warn on shutdown — the same reason the capture device is closed
    here rather than left to garbage collection.
    """
    global _previews, _failed
    _built.clear()
    _unavailable.clear()
    _failed = False
    if _previews is None:
        return
    try:
        bpy.utils.previews.remove(_previews)
    except Exception:
        logger.debug("[Voice] preview collection already released", exc_info=True)
    _previews = None
