# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Getting the marks onto the message.

One entry point each way, called from the chat send operator:

* :func:`prepare_for_send` — build the mark payload and attach the frozen
  frames, returning the dict that rides beside ``project_context``.
* :func:`finish_send` — flip the drafts to SENT and leave Scribble on both
  surfaces (the freeze and the chat handwriting canvas).

Both are best-effort by contract. The user's words are a complete request on
their own; losing the whole message because an optional attachment failed to
pack would be far worse than losing the illustration.

The frames are attached **annotated first, clean second**. If the composer is
near its attachment cap only one survives, and the annotated copy is the one
carrying information the agent cannot get any other way — the clean frame it
can always re-render from the baked camera.
"""

from __future__ import annotations

import json

import bpy

from mixar.config.logging_config import get_logger

from . import annotate, freeze, marks as mark_store, view_bake
from . import payload as payload_mod

logger = get_logger(__name__)


def prepare_for_send(scene):
    """``(mark_context, notes)`` for this turn, or ``(None, [])``.

    The payload is built under the user's reading override (the header
    dropdown / Tab) and then run through the context budget: what goes on
    the wire is exactly what ``serialize`` says fits, and anything shed is
    reported in *notes* rather than silently missing.
    """
    try:
        wm = bpy.context.window_manager
        context = mark_store.build_context(
            scene, drafts_only=True,
            intent_override=mark_store.intent_override(wm),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Scribble mark: could not build mark context: %s", exc,
                       exc_info=True)
        return None, []

    if not context:
        return None, []

    notes = []
    try:
        text, shed = payload_mod.serialize(context)
        context = json.loads(text)
        notes.extend(shed)
    except Exception as exc:  # noqa: BLE001 — over budget is better than lost
        logger.warning("Scribble mark: budget pass failed, sending as built: %s",
                       exc)

    try:
        notes.extend(_attach_frames(scene, context))
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
        # The reading override belongs to the ink that just went; the next
        # freeze starts on Auto. (Its update callback re-reads the drafts,
        # which are now SENT, and clears the hint.)
        wm = bpy.context.window_manager
        if getattr(wm, "mixar_mark_intent", "AUTO") != "AUTO":
            wm.mixar_mark_intent = "AUTO"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scribble mark: could not reset the reading: %s", exc)

    try:
        # Sending is the end of the gesture on BOTH surfaces. Leaving the
        # viewport frozen afterwards traps the user behind a still they have
        # finished with, and leaving the chat canvas up would swallow their
        # next click into the composer.
        from . import scribble_mode

        scribble_mode.disarm(bpy.context.window_manager)
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
    # is never overwritten by a later freeze. Drawn from the STORED records,
    # which still carry the raw strokes the wire payload leaves behind.
    marks = context.get("marks") or ()
    serial = marks[-1].get("id") if marks else 0
    all_ink = mark_store.draft_marks(scene) or marks

    # The annotated copy is THIS frame, so only ink drawn ON it lands where
    # the user put it. A draft from an earlier freeze — the mode was re-armed,
    # or the viewport resized mid-mode — describes a different camera and
    # framing; converting its normalized strokes against this frame's size
    # would ink them where the user never drew, on the one picture the agent
    # is told shows the marks. Those marks still travel whole: their resolved
    # data and the prose describe them, and their own view rides the views map.
    current_view = view_bake.view_name_for_frame(frame_name)
    own = [m for m in all_ink if m.get("view") == current_view]
    omitted = len(all_ink) - len(own)

    annotated = None
    if own:
        annotated = annotate.render_annotated(
            image, own, freeze.annotated_name(serial),
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
        if omitted:
            notes.append("the newest frame carries none of the marks; "
                         "it is attached clean")
        else:
            notes.append("the marks could not be drawn onto the frame")
    elif omitted:
        notes.append(
            f"{omitted} earlier mark(s) were drawn on a previous frame; "
            "their resolved data describes them, but their ink is not on "
            "the attached frame"
        )

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
