# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Getting the marks onto the message.

One entry point each way, called from the chat send operator:

* :func:`prepare_for_send` — build the mark payload and attach the frozen
  frames, returning the dict that rides beside ``project_context``.
* :func:`finish_send` — flip the drafts to SENT and lower the freeze.

Both are best-effort by contract. The user's words are a complete request on
their own; losing the whole message because an optional attachment failed to
pack would be far worse than losing the illustration.

The frames are attached **annotated first, clean second**. If the composer is
near its attachment cap only one survives, and the annotated copy is the one
carrying information the agent cannot get any other way — the clean frame it
can always re-render from the baked camera.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

from . import annotate, freeze, marks as mark_store

logger = get_logger(__name__)


def prepare_for_send(scene):
    """``(mark_context, notes)`` for this turn, or ``(None, [])``."""
    try:
        context = mark_store.build_context(scene, drafts_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not build mark context: %s", exc,
                       exc_info=True)
        return None, []

    if not context:
        return None, []

    notes = []
    try:
        notes = _attach_frames(scene, context)
    except Exception as exc:  # noqa: BLE001 — an attachment is never worth
        # losing the marks, which carry the resolved answer on their own
        logger.warning("Scribble mark: could not attach frozen frames: %s", exc,
                       exc_info=True)

    return context, notes


def finish_send(scene):
    """Called once the message is away: settle the marks and lower the freeze.

    The marks are kept, not cleared. They are what a follow-up turn refers
    back to, and the vertex groups and cameras they name are still live.
    """
    try:
        mark_store.mark_all_sent(scene)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not settle marks: %s", exc)

    try:
        wm = bpy.context.window_manager
        if getattr(wm, "mixar_mark_armed", False):
            # Sending is the end of the gesture. Leaving the viewport frozen
            # afterwards traps the user behind a still they have finished with.
            wm.mixar_mark_armed = False
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not disarm after send: %s", exc)


# =============================================================================
# Frames
# =============================================================================

def _attach_frames(scene, context):
    """Attach the annotated and clean frozen frames. Returns any notes."""
    from mixar.modules.space_mixie_chat.constants import (
        MAX_ATTACHMENTS_PER_MESSAGE,
    )

    frame_name = getattr(scene, "mixar_mark_frame_name", "") or ""
    image = freeze.get_image(frame_name) if frame_name else None
    if image is None:
        return ["the frozen frame was unavailable; marks sent without it"]

    # Named off the newest mark's serial, so an earlier message's attachment
    # is never overwritten by a later freeze.
    marks = context.get("marks") or ()
    serial = marks[-1].get("id") if marks else 0
    annotated = annotate.render_annotated(
        image, marks, freeze.annotated_name(serial)
    )

    pending = scene.mixie_chat_pending_attachments
    room = MAX_ATTACHMENTS_PER_MESSAGE - len(pending)
    if room <= 0:
        return ["no attachment slots left; marks sent without the frame"]

    notes = []
    # Annotated first: it is the only view of the marks in context, and the
    # clean frame is reproducible from the baked camera at any time.
    queued = 0
    for name in (annotated, frame_name):
        if not name or queued >= room:
            continue
        if _already_attached(pending, name):
            continue
        _attach(pending, name)
        queued += 1

    if annotated and queued == 1 and room == 1:
        notes.append("only the marked frame fit; the clean frame was not attached")
    if not annotated:
        notes.append("the marks could not be drawn onto the frame")

    return notes


def _already_attached(pending, name):
    return any(
        att.image_source == "BLEND_DATA" and att.image_path == name
        for att in pending
    )


def _attach(pending, image_name):
    """Queue a packed datablock as a chat attachment.

    BLEND_DATA rather than FILE: both frames are packed into the .blend and
    have no file on disk to point at — they live in ``bpy.app.tempdir`` only
    for the moment between capture and pack.
    """
    attachment = pending.add()
    attachment.image_source = "BLEND_DATA"
    attachment.image_path = image_name
    attachment.display_name = image_name
