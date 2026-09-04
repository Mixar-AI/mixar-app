# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One Scribble mode, two surfaces.

Arming Scribble means: ink over the chat becomes TEXT in the composer, and
ink over the 3D viewport becomes MARKS the agent resolves against the scene.
The user chooses by where they write, never by which button they pressed.

This module is only the coordinator. Each half already owns itself:

* the chat half is the C++ ink canvas, whose visibility flag and recognition
  queue live in ``space_mixie_chat/core/scribble.py``;
* the viewport half is the freeze modal in ``ui/operators/mark_draw_ops.py``,
  driven by ``WindowManager.mixar_mark_armed``.

What is decided here is that they enter and leave TOGETHER. Esc over either
surface, the header toggle, and sending a message all end both halves — a
mode whose two halves can drift apart is two modes the user has to track.

Every call is tolerant of one half being absent: a build without the ink
canvas still gets marks, and a layout without a 3D viewport still gets
handwriting.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _ink():
    """The chat half, imported late: the chat ``core`` package pulls in the
    connection manager, which must not be a cost of importing this module."""
    from mixar.modules.space_mixie_chat.core import scribble

    return scribble


# =============================================================================
# Reading
# =============================================================================

def ink_available(wm) -> bool:
    """Whether this build has the handwriting canvas at all."""
    try:
        return bool(_ink().canvas_available(wm))
    except Exception:  # noqa: BLE001 — chat module missing is "no canvas"
        return False


def ink_open(wm) -> bool:
    """Whether the handwriting canvas is up over the chat surfaces."""
    try:
        return bool(_ink().is_canvas_open(wm))
    except Exception:  # noqa: BLE001
        return False


def marks_armed(wm) -> bool:
    """Whether the viewport freeze is up."""
    return bool(getattr(wm, "mixar_mark_armed", False))


def is_armed(wm) -> bool:
    """Scribble is on when EITHER half is up: the header button shows one
    state, and clicking it while any half is up turns everything off."""
    return marks_armed(wm) or ink_open(wm)


# =============================================================================
# Writing
# =============================================================================

def open_ink(wm) -> bool:
    """Raise the handwriting canvas. False when this build has none."""
    try:
        return bool(_ink().open_canvas(wm))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble: could not open the handwriting canvas: %s", exc)
        return False


def close_ink(wm) -> None:
    """Lower the handwriting canvas, converting what is still on it first."""
    try:
        _ink().close_canvas(wm)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble: could not close the handwriting canvas: %s", exc)


def arm(context, report=None) -> bool:
    """Enter Scribble on every surface that exists. True if any half armed.

    The canvas is raised BEFORE the freeze modal starts, so the modal can
    record that it is linked to the chat half and follow it down when the
    user closes the canvas from the chat side (a C++ path Python never sees).
    """
    wm = context.window_manager
    opened = open_ink(wm)

    froze = False
    try:
        result = bpy.ops.mixar.scribble_mark_draw("INVOKE_DEFAULT")
        froze = "RUNNING_MODAL" in result
    except RuntimeError as exc:
        # The modal already reported the ordinary refusals (no viewport,
        # camera view, capture failure); this is the unexpected kind.
        if report is not None:
            report({"WARNING"}, f"Could not freeze the viewport: {exc}")

    if not froze and not opened:
        return False
    return True


def disarm(wm) -> None:
    """Leave Scribble on both surfaces.

    Order matters. The chat half is closed FIRST so that a recognition
    request for the last handwritten words is already in flight when the
    marks settle; the freeze modal then sees the armed flag drop on its next
    event and lowers itself.
    """
    close_ink(wm)
    if marks_armed(wm):
        wm.mixar_mark_armed = False
