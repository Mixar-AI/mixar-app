# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Draft sketch previews and their agent-only clean companions.

The composer owns only annotated images. Clean frames join a transient send
list, so they cannot appear as duplicate references or in message history.
One preview belongs to one frozen view; removing it also discards that view's
draft ink. Sent images and marks are never removed by draft cleanup.
"""

from types import SimpleNamespace

from . import annotate, freeze, marks as mark_store


def frame_for_view(view):
    from ..constants import MARK_CAMERA_PREFIX

    prefix, separator, serial = (view or "").rpartition("_")
    if prefix + separator != MARK_CAMERA_PREFIX or not serial.isdigit():
        return ""
    return freeze.frame_name(int(serial))


def sync(scene):
    """Materialize every draft view after Done/Escape or before Send.

    Called from operators, never draw callbacks. Existing packed previews are
    reused, so repeated sends/preflight retries do not redraw or duplicate them.
    Returns actionable notes when a preview cannot be made or attached.
    """
    from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE
    from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas

    pending = scene.mixie_chat_pending_attachments
    groups = {}
    for mark in mark_store.draft_marks(scene):
        groups.setdefault(mark.get("view", ""), []).append(mark)
    wanted = {view: freeze.annotated_name(marks[-1]["id"])
              for view, marks in groups.items()}
    for index in reversed(range(len(pending))):
        att = pending[index]
        view = getattr(att, "scribble_view", "")
        if view and wanted.get(view) != att.image_path:
            name = att.image_path
            pending.remove(index)
            _release_unused_preview(scene, name)

    notes = []
    for view, marks in groups.items():
        name = wanted[view]
        existing = next((att for att in pending
                         if att.image_source == "BLEND_DATA" and att.image_path == name), None)
        if existing is not None and freeze.get_image(name) is not None:
            existing.scribble_view = view
            continue
        if existing is None and len(pending) >= MAX_ATTACHMENTS_PER_MESSAGE:
            notes.append("Remove a reference to make room for the sketch preview.")
            continue
        if freeze.get_image(name) is None:
            frame = freeze.get_image(frame_for_view(view))
            if frame is None or not annotate.render_annotated(frame, marks, name):
                notes.append("Could not create the sketch preview. Draw again to retry.")
                continue
        att = existing if existing is not None else pending.add()
        att.image_source = "BLEND_DATA"
        att.image_path = name
        att.display_name = "View sketch"
        att.scribble_view = view
    redraw_chat_areas()
    return notes


def outgoing_attachments(scene):
    """Snapshot visible attachments, then append clean frames within the cap.

    Visible references always take priority. This list is used for encoding
    and attachment names only; the optimistic transcript copies the composer.
    """
    from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE

    pending = scene.mixie_chat_pending_attachments
    result = list(pending)
    names = {att.image_path for att in pending if att.image_source == "BLEND_DATA"}
    for att in pending:
        frame = frame_for_view(getattr(att, "scribble_view", ""))
        if not frame or frame in names or freeze.get_image(frame) is None:
            continue
        if len(result) >= MAX_ATTACHMENTS_PER_MESSAGE:
            break
        result.append(SimpleNamespace(image_source="BLEND_DATA", image_path=frame,
                                      display_name=frame, imported_object_names=""))
        names.add(frame)
    return result


def discard_view(scene, wm, view):
    """Remove exactly the draft ink represented by a preview's × button."""
    from . import overlay
    from mixar.modules.scribble_mark.ui.operators.mark_draw_ops import live_view_name

    live_view = live_view_name()
    mark_store.clear(scene, drafts_only=True, view=view, keep_view=live_view)
    if view != live_view and not mark_store.view_referenced(scene, view):
        freeze.release(frame_for_view(view))
    sync(scene)
    if not mark_store.has_drafts(scene) and wm.mixar_mark_intent != "AUTO":
        wm.mixar_mark_intent = "AUTO"
    mark_store.refresh_reading(scene, wm)
    overlay.tag_redraw()


def _release_unused_preview(scene, name):
    if any(att.image_source == "BLEND_DATA" and att.image_path == name
           for message in scene.mixie_chat_messages for att in message.attachments):
        return
    freeze.release(name)
