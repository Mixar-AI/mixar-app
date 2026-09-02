# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Making sure a file load can never leave the viewport frozen.

Modal operators do not survive a ``.blend`` load — Blender tears the running
instance down when it rebuilds the screens. Two pieces of state DO survive,
because they are Python module state rather than RNA: the modal's ``_running``
guard and the overlay's draw handler.

Left alone that combination is the worst possible outcome: the overlay keeps
painting a stale frozen frame over the viewport, the guard says a modal is
already running so a fresh one refuses to start, and nothing is left listening
for the disarm. The user is looking at a picture of a scene they can no longer
navigate, with no way out but a restart.

``mixar_mark_armed`` is ``SKIP_SAVE``, so it comes back False on its own; this
handler cleans up the two things that would not.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.scribble_mark.core import overlay

logger = get_logger(__name__)


@persistent
def _on_load_post(_dummy):
    """Tear down any freeze the outgoing file left behind."""
    try:
        from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
        mark_draw_ops.reset_running_guard()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not reset the modal guard: %s", exc)

    try:
        overlay.remove()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not remove the overlay: %s", exc)

    try:
        wm = getattr(bpy.context, "window_manager", None)
        if wm is not None and getattr(wm, "mixar_mark_armed", False):
            wm.mixar_mark_armed = False
        # The reading override is SKIP_SAVE too, but a load without a restart
        # keeps the WindowManager — and it described the OLD file's ink.
        if wm is not None and getattr(wm, "mixar_mark_intent", "AUTO") != "AUTO":
            wm.mixar_mark_intent = "AUTO"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not clear the armed flag: %s", exc)

    # The chat half's recognition queue is Python module state too: a batch
    # in flight for the OLD file must not append its text into the new one.
    try:
        from mixar.modules.space_mixie_chat.core import scribble

        scribble.reset_state()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble: could not reset the handwriting queue: %s", exc)


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    # Disabling the add-on mid-freeze must not leave a handler painting into
    # a viewport whose operators no longer exist.
    try:
        overlay.remove()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: overlay teardown on unregister: %s", exc)
