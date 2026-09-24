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

Only annotated previews enter the composer and transcript. Clean companion
frames join the outgoing encoding list in preview.outgoing_attachments;
visible references take priority when the attachment cap is reached.
"""

from __future__ import annotations

import json

import bpy

from mixar.config.logging_config import get_logger

from . import marks as mark_store, preview
from . import payload as payload_mod

logger = get_logger(__name__)


def flush_for_send(context):
    """Resolve the final stroke now, without waiting for another modal timer."""
    from . import pending

    pending.flush(context)


def default_message(scene, wm):
    """Allow ink-only sends without inventing an edit for an ambiguous pointer."""
    context = mark_store.build_context(
        scene, drafts_only=True, intent_override=mark_store.intent_override(wm),
    )
    if not context:
        return ""
    if context.get("intent") == "sketch" and context.get("sketch"):
        return "Build what I drew in this sketch."
    return "Use these marks as context; ask me what to change if it is unclear."


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
        notes.extend(preview.sync(scene))
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
