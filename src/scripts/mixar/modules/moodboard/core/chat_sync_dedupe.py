# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Composer ↔ moodboard attachment identity.

A board image and a composer attachment can name the same picture in two
ways. A ``BLEND_DATA`` attachment carries the ``bpy.data.images`` NAME, which
is also how the board references its media, so those compare by name. A
``FILE`` attachment carries the PATH the user dropped / pasted / captured,
and the board mirror (``attachment_board_sync``) loads that same file into a
packed datablock that keeps the path in ``image.filepath`` — so a FILE
attachment and its boarded twin only agree on the FILE, never on a name.

``chat_sync`` (board selection → composer) and the composer's own attach /
remove operators must apply ONE notion of "already attached", or the same
picture shows up as two pills: the dropped file and its selected board copy.
This module is that one notion. It is kept ``bpy``-light (only the
``bpy.data.images`` lookup and ``bpy.path.abspath`` are touched, both
defensively) so the logic runs under the test suite's ``bpy`` mock.
"""

from __future__ import annotations

import os

import bpy


def file_key(path: str) -> str:
    """Normalized identity of a file path, or ``""`` when unusable.

    Resolves Blender-relative (``//``) paths when ``bpy.path`` can, then
    canonicalizes through ``realpath``/``normcase`` so two spellings of one
    file compare equal.
    """
    if not path or not isinstance(path, str):
        return ""
    resolved = path
    try:
        candidate = bpy.path.abspath(path)
        if isinstance(candidate, str) and candidate:
            resolved = candidate
    except Exception:  # noqa: BLE001 — path resolution is never worth raising
        pass
    try:
        return os.path.normcase(os.path.realpath(resolved))
    except Exception:  # noqa: BLE001
        return ""


def image_file_key(image) -> str:
    """``file_key`` of the file an Image datablock was loaded from.

    ``""`` for generated / render images and anything without a usable path.
    """
    if image is None:
        return ""
    filepath = getattr(image, "filepath", "")
    if not isinstance(filepath, str):
        return ""
    return file_key(filepath)


def attachment_identity_sets(attachments) -> tuple[set[str], set[str]]:
    """Split ``pending_attachments`` into the two identities they carry.

    Returns ``(blend_names, file_keys)``: the image NAMES of every
    ``BLEND_DATA`` attachment (moodboard-origin or manual) and the
    normalized file keys of every ``FILE`` attachment. ``MODEL_FILE``
    attachments are not images and contribute to neither.
    """
    blend_names: set[str] = set()
    file_keys: set[str] = set()
    for att in attachments:
        source = getattr(att, "image_source", "")
        path = getattr(att, "image_path", "")
        if source == 'BLEND_DATA' and path:
            blend_names.add(path)
        elif source == 'FILE':
            key = file_key(path)
            if key:
                file_keys.add(key)
    return blend_names, file_keys


def board_image_is_attached(
    image_name: str, blend_names: set[str], file_keys: set[str], images=None
) -> bool:
    """True when some composer attachment already shows board image *image_name*.

    A ``BLEND_DATA`` attachment matches by name. A ``FILE`` attachment matches
    when the board image was loaded from the attached file — the case of a
    picture dropped into the chat, mirrored onto the board, then selected
    there. *images* defaults to ``bpy.data.images``.
    """
    if image_name in blend_names:
        return True
    if not file_keys:
        return False
    if images is None:
        images = bpy.data.images
    try:
        image = images.get(image_name)
    except Exception:  # noqa: BLE001
        return False
    key = image_file_key(image)
    return bool(key) and key in file_keys


def attachment_shows_board_item(mb_img, image_path: str, image_source: str) -> bool:
    """Does the composer attachment ``(image_path, image_source)`` show the
    picture of moodboard media item *mb_img*?

    The inverse lookup of :func:`board_image_is_attached`, used when a pill is
    removed so the board item it stood for is deselected too — otherwise the
    selection sync re-attaches it on the next poll and the X appears to do
    nothing.
    """
    image = getattr(mb_img, "image", None)
    if image is None:
        return False
    if image_source == 'BLEND_DATA':
        return getattr(image, "name", None) == image_path
    if image_source == 'FILE':
        key = file_key(image_path)
        return bool(key) and image_file_key(image) == key
    return False
