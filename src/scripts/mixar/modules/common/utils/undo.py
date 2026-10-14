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


def push_undo_step(message: str) -> bool:
    """Push a named undo checkpoint, borrowing a window if there is none.

    Returns True only when a checkpoint was actually created. Never raises:
    callers run inside job completion handlers where an exception would
    strand the job.
    """
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
