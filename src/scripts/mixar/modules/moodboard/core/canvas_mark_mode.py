# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas Annotate/Erase mode: WindowManager flags that every other tool clears.

The flags are sticky by design (release finishes a stroke and leaves the
pencil armed), so the only exits are Esc, the tool's own button, a USER
drawer close -- and, through ``exit_canvas_mark_mode``, picking any other
canvas tool. Without that last one the Text tool placed its box while the
pencil stayed armed, and the very next click drew a stroke again.
"""

from .canvas_context import redraw_moodboard_canvases


def canvas_mark_mode(window_manager):
    """``(annotating, erasing)``; attribute-tolerant because the props register late."""
    return (
        bool(getattr(window_manager, "mixie_moodboard_annotating", False)),
        bool(getattr(window_manager, "mixie_moodboard_erasing", False)),
    )


def set_canvas_mark_mode(context, *, annotating=False, erasing=False):
    wm = context.window_manager
    wm.mixie_moodboard_annotating = bool(annotating)
    if hasattr(wm, "mixie_moodboard_erasing"):
        wm.mixie_moodboard_erasing = bool(erasing)
    if annotating or erasing:
        context.scene.mixie_moodboard_show_annotations = True
    redraw_moodboard_canvases()


def exit_canvas_mark_mode(context):
    """Release Annotate/Erase because another canvas tool took over.

    Returns True when a mode was actually on. Safe to call from any tool
    entry point, including property update callbacks.
    """
    wm = getattr(context, "window_manager", None)
    if wm is None or not any(canvas_mark_mode(wm)):
        return False
    set_canvas_mark_mode(context, annotating=False, erasing=False)
    return True
