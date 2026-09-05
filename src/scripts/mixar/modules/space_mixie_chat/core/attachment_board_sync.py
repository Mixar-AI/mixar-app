# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Chat composer → moodboard mirroring.

Every image the user attaches in the agent chat also lands on the scene's
moodboard, so the board stays the single visual record of what the session
has been working with. This is the counterpart of
``moodboard.core.chat_sync`` (moodboard selection → composer attachments):
that module owns the *moodboard-origin* attachments and its images are
already on the board, so they are skipped here.

Mirroring is best-effort by contract — a failure to board an image must
never block the attach itself, which is the action the user asked for.

Boarded items are deliberately added **unselected**. A selected board item
is mirrored straight back into ``pending_attachments`` by ``chat_sync``,
which would show the user a second pill for the image they just attached.
"""

from __future__ import annotations

import os

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _same_file(a: str, b: str) -> bool:
    """Compare two (possibly Blender-relative) paths defensively."""
    if not a or not b:
        return False
    try:
        return os.path.realpath(bpy.path.abspath(a)) == os.path.realpath(
            bpy.path.abspath(b)
        )
    except Exception:  # noqa: BLE001 — path comparison is never worth raising
        return False


def _board_items(scene):
    """The scene's moodboard media collection, or None when unavailable."""
    return getattr(scene, "mixie_moodboard_images", None)


def _find_on_board(scene, *, image=None, filepath: str = ""):
    """Return the board item already showing this image/file, else None."""
    items = _board_items(scene)
    if items is None:
        return None
    for item in items:
        img = item.image
        if img is None:
            continue
        if image is not None and img == image:
            return item
        if filepath and _same_file(getattr(img, "filepath", ""), filepath):
            return item
    return None


def _add_blend_image_to_board(scene, image_name: str):
    """Board an existing ``bpy.data.images`` datablock by name."""
    image = bpy.data.images.get(image_name)
    if image is None or image.type in {'RENDER_RESULT', 'COMPOSITING'}:
        return None
    if _find_on_board(scene, image=image) is not None:
        return None

    from mixar.modules.moodboard.core.media_import import add_packed_image_to_board

    # Generated / painted images carry their pixels in memory only; packing
    # keeps the board item valid after a save+reload. Movies cannot be packed
    # and are not attachable in the first place.
    if image.source not in {'MOVIE', 'SEQUENCE'} and not image.packed_file:
        try:
            image.pack()
        except Exception:  # noqa: BLE001 — an unpackable image still boards fine
            logger.debug("Could not pack %s for the moodboard", image_name, exc_info=True)

    return add_packed_image_to_board(scene, image, selected=False)


def _add_file_to_board(scene, filepath: str):
    """Board an image file, reusing the moodboard's own import path."""
    if not filepath or not os.path.isfile(bpy.path.abspath(filepath)):
        return None
    if _find_on_board(scene, filepath=filepath) is not None:
        return None

    from mixar.modules.moodboard.core.media_import import load_media_file_to_board

    # The moodboard's loader packs stills, so a paste/screenshot living in the
    # temp directory survives that directory being cleaned up.
    return load_media_file_to_board(scene, bpy.path.abspath(filepath))


def find_attachment_for_file(attachments, filepath: str):
    """Return the pending attachment already showing *filepath*, else None.

    A ``FILE`` attachment matches on the file itself. A ``BLEND_DATA`` one
    matches when its datablock was loaded from that file — which is what a
    moodboard-origin pill for a previously dropped image looks like, since the
    board mirror loads the dropped file and keeps its ``filepath``. Without the
    second rule, re-dropping a file whose board copy is selected showed the
    picture twice. Shares its identity rules with ``moodboard.core.chat_sync``
    (``chat_sync_dedupe``), which de-dupes in the other direction.
    """
    if not filepath:
        return None
    for att in attachments:
        source = getattr(att, "image_source", "")
        path = getattr(att, "image_path", "")
        if source == 'FILE':
            if path == filepath or _same_file(path, filepath):
                return att
        elif source == 'BLEND_DATA' and path:
            image = bpy.data.images.get(path)
            if image is None:
                continue
            if _same_file(getattr(image, "filepath", ""), filepath):
                return att
    return None


def _redraw_moodboard_areas() -> None:
    """Tag MIXIE areas so a newly boarded item shows up immediately."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
                    for region in area.regions:
                        region.tag_redraw()
    except Exception:  # noqa: BLE001
        logger.debug("moodboard redraw failed", exc_info=True)


def mirror_attachment_to_moodboard(scene, image_path: str, image_source: str) -> bool:
    """Add a chat attachment's image to *scene*'s moodboard.

    Args:
        scene: Scene owning both the composer and the moodboard.
        image_path: File path (``FILE``) or ``bpy.data.images`` name
            (``BLEND_DATA``) — i.e. the attachment's ``image_path``.
        image_source: ``'FILE'`` or ``'BLEND_DATA'``.

    Returns:
        True when a new board item was created. False when the image was
        already on the board, the moodboard is unavailable, or the import
        failed — never raises.
    """
    if scene is None or _board_items(scene) is None:
        return False

    try:
        if image_source == 'FILE':
            item = _add_file_to_board(scene, image_path)
        elif image_source == 'BLEND_DATA':
            item = _add_blend_image_to_board(scene, image_path)
        else:
            return False
    except Exception:  # noqa: BLE001 — mirroring must never block the attach
        logger.debug(
            "Could not mirror attachment to moodboard: %s", image_path, exc_info=True
        )
        return False

    if item is None:
        return False

    _redraw_moodboard_areas()
    return True


def mirror_attachment(scene, attachment) -> bool:
    """Convenience wrapper: mirror a pending-attachment RNA item.

    Moodboard-origin attachments are skipped — their image is on the board
    already, and it is the board that put them in the composer.
    """
    if attachment is None or getattr(attachment, "is_moodboard", False):
        return False
    return mirror_attachment_to_moodboard(
        scene, attachment.image_path, attachment.image_source
    )
