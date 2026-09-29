# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo checkpoints for work that lands outside an operator.

Every async generation result -- a downloaded model, a moodboard image, a
MatGen material, a World Labs world -- is applied from a ``bpy.app.timers``
tick. That context carries no window, and ``ed.undo_push`` polls
``ED_operator_screenactive`` (window + screen), so a bare push there fails
its poll and the result never enters the undo stack.

The consequence is worse than "no undo for the generation": Blender's next
Ctrl+Z steps back to the checkpoint *before* the import, so pressing undo
once for the artist's own last action reverts the scene to a state that
predates the generated object -- and the forward redo step predates it too,
so a paid asset is gone past redo.

``push_undo_step`` retries inside a borrowed window, which is what
``space_mixie_chat.core.executor`` already does for agent scripts.
"""

from __future__ import annotations

import logging

import bpy

logger = logging.getLogger(__name__)

__all__ = ["push_undo_step"]


def push_undo_step(message: str, scene=None) -> bool:
    """Push a named undo checkpoint, borrowing a window if there is none.

    ``scene`` names the scene tab the step belongs to. Job results, generation
    results and other timer-context work land while the window shows whatever
    the user looks at; per-tab undo tags a step with the window's tab, so a
    result for tab A pushed without ``scene`` would join the user's tab, break
    that tab's redo and vanish from A's history. Builds with
    ``WindowManager.mixar_undo_push`` take the tab explicitly (a one-shot C
    override around ED_undo_push, no window needed); without ``scene`` the
    context scene is named, which is the window's tab, as before.

    Returns True only when a checkpoint was actually created. Never raises:
    callers run inside job completion handlers where an exception would
    strand the job.
    """
    wm = getattr(bpy.context, "window_manager", None)
    pusher = getattr(wm, "mixar_undo_push", None)
    if pusher is not None:
        try:
            target = scene if scene is not None else getattr(bpy.context, "scene", None)
            if target is not None:
                pusher(message, scene=target)
            else:
                pusher(message)
            return True
        except (RuntimeError, AttributeError, TypeError):
            logger.debug("mixar_undo_push failed; falling back to ed.undo_push", exc_info=True)
    try:
        bpy.ops.ed.undo_push(message=message)
        return True
    except (RuntimeError, AttributeError):
        pass
    try:
        windows = bpy.context.window_manager.windows
        if not windows:
            return False
        with bpy.context.temp_override(window=windows[0]):
            bpy.ops.ed.undo_push(message=message)
        return True
    except (RuntimeError, AttributeError, TypeError):
        logger.warning(
            "Undo checkpoint %r could not be created - this change may not be "
            "individually undoable",
            message,
        )
        return False
