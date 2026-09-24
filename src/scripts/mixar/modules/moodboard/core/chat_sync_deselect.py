# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Release board selection when a moodboard-origin chat pill is removed."""

from __future__ import annotations

from .chat_sync_dedupe import attachment_shows_board_item


def _release_frames_and_nodes_for_attachment(
    scene, image_path: str, image_source: str
) -> bool:
    """Drop the selected frame or generated node that staged this pill."""
    changed = False
    matched_frames = {
        getattr(item, "frame_id", "")
        for item in getattr(scene, "mixie_moodboard_images", ()) or ()
        if attachment_shows_board_item(item, image_path, image_source)
    }
    matched_frames.discard("")
    for frame in getattr(scene, "mixie_moodboard_frames", ()) or ():
        if frame.selected and getattr(frame, "frame_id", "") in matched_frames:
            frame.selected = False
            changed = True
    for node in getattr(scene, "mixie_moodboard_action_nodes", ()) or ():
        preview = getattr(node, "preview_image", None)
        if (
            getattr(node, "selected", False)
            and preview is not None
            and image_source == 'BLEND_DATA'
            and getattr(preview, "name", None) == image_path
        ):
            node.selected = False
            changed = True
    return changed


def deselect_moodboard_image_for_attachment(
    scene, image_path: str, image_source: str
) -> bool:
    """Deselect every moodboard image the composer attachment
    ``(image_path, image_source)`` stands for. Returns True if at least
    one image was deselected.

    Called from the chat composer's X-button so removing a pill also
    drops the board selection — otherwise the next poll would re-add it.
    Selected frames and generated nodes that staged the pill are released
    too. FILE pills use the same identity rules as their board copies.
    """
    from .chat_sync import force_resync, _redraw_moodboard_areas

    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return False
    changed = False
    for mb_img in images_attr:
        if not mb_img.selected:
            continue
        if attachment_shows_board_item(mb_img, image_path, image_source):
            mb_img.selected = False
            changed = True
    if _release_frames_and_nodes_for_attachment(scene, image_path, image_source):
        changed = True
    if changed:
        force_resync(scene)
        _redraw_moodboard_areas()
    return changed


def deselect_moodboard_image_by_name(scene, image_name: str) -> bool:
    """Name-only form of :func:`deselect_moodboard_image_for_attachment`."""
    return deselect_moodboard_image_for_attachment(scene, image_name, 'BLEND_DATA')


def deselect_all_moodboard_origin_attachments(scene) -> int:
    """Deselect every moodboard image (and any frame that carried it in)
    whose corresponding ``is_moodboard`` attachment is in
    ``pending_attachments``. Called from the chat send paths BEFORE
    ``pending_attachments.clear()`` so moodboard selections don't
    auto-re-attach on the next poll after the message goes out.

    Returns the number of moodboard items deselected.
    """
    from .chat_sync import force_resync, _redraw_moodboard_areas

    images_attr = getattr(scene, "mixie_moodboard_images", None)
    frames_attr = getattr(scene, "mixie_moodboard_frames", None)
    attachments = getattr(scene, "mixie_chat_pending_attachments", None)
    if images_attr is None or attachments is None:
        return 0

    moodboard_attached_names = {
        att.image_path for att in attachments
        if getattr(att, "is_moodboard", False) and att.image_path
    }
    if not moodboard_attached_names:
        return 0

    # A selected FRAME attaches its whole contents, so an attachment can
    # come from an image that was never selected in its own right. Deselect
    # the frames that were sent as well as the images — otherwise the next
    # poll re-attaches every member of a still-selected frame.
    count = 0
    sent_frame_ids = set()
    for mb_img in images_attr:
        if mb_img.image is None:
            continue
        if mb_img.image.name not in moodboard_attached_names:
            continue
        frame_id = getattr(mb_img, "frame_id", "")
        if frame_id:
            sent_frame_ids.add(frame_id)
        if mb_img.selected:
            mb_img.selected = False
            count += 1

    if frames_attr is not None:
        for frame in frames_attr:
            if getattr(frame, "frame_id", "") in sent_frame_ids and frame.selected:
                frame.selected = False
                count += 1

    for node in getattr(scene, "mixie_moodboard_action_nodes", ()) or ():
        preview = getattr(node, "preview_image", None)
        if (
            getattr(node, "selected", False)
            and preview is not None
            and getattr(preview, "name", "") in moodboard_attached_names
        ):
            node.selected = False
            count += 1

    if count:
        force_resync(scene)
        _redraw_moodboard_areas()
    return count
