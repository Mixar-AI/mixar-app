# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Independent viewport annotation and explicitly opened handwriting.

Annotation leaves the composer available for typing and Voice. Handwriting
owns only the chat canvas. Send closes both after flushing their pending ink.
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
    """The Sketch control reflects only the viewport freeze."""
    return marks_armed(wm)


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
    """Freeze the viewport without changing the prompt input method."""
    try:
        result = bpy.ops.mixar.scribble_mark_draw("INVOKE_DEFAULT")
        if "RUNNING_MODAL" in result:
            from . import island
            island.minimize()
            return True
    except RuntimeError as exc:
        logger.warning("Sketch: could not freeze the viewport: %s", exc)
    _warn_marking_unavailable(context, report)
    return False


def marking_unavailable_reason(context) -> str | None:
    """Why the viewport half cannot arm, in the user's words, or ``None``.

    Mirrors the modal's own refusals (``mark_draw_ops.invoke``) so the
    message names the thing to change rather than "could not freeze".
    """
    from .freeze_session import find_view3d

    try:
        _window, area, region = find_view3d(context)
    except Exception:  # noqa: BLE001
        return None
    if area is None or region is None:
        return "no 3D viewport is open"
    rv3d = getattr(getattr(area.spaces, "active", None), "region_3d", None)
    if getattr(rv3d, "view_perspective", "") == "CAMERA":
        return "the viewport is in camera view"
    return None


def _warn_marking_unavailable(context, report=None) -> None:
    """Report refusals visibly even when invoked from the floating island."""
    reason = marking_unavailable_reason(context) or "the viewport could not be frozen"
    if report is not None:
        report({"WARNING"}, f"Cannot sketch: {reason}")
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push(
            "warning",
            f"Cannot sketch: {reason}",
            "Open a 3D viewport outside camera view (Numpad 0 leaves it), then try again.",
            id="scribble_annotation_unavailable",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Sketch: could not show the notice: %s", exc)


def disarm_marks(wm) -> None:
    """Stop viewport annotation, keeping handwriting and the draft intact."""
    if marks_armed(wm):
        wm.mixar_mark_armed = False


def disarm(wm) -> None:
    """Finish both tools on Send, converting the final handwriting first."""
    close_ink(wm)
    disarm_marks(wm)
