# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One-way conversion of a pre-frame board's ``group_index`` groups.

Split out of ``frames.py`` for the 500-line rule, and the seam is the natural
one: everything here runs ONCE per legacy board and then never again, while
``frames.py`` is the live membership rule every gesture goes through.

``frames.migrate_legacy_groups`` stays the public entry point and forwards
here, so call sites and the module's own docstring are unchanged.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from .frames import _frames, _is_node_owned, create_frame

logger = get_logger(__name__)


def migrate_legacy_groups(scene) -> int:
    """Turn a pre-frame board's ``group_index`` groups into real frames.

    Idempotent and one-way: the legacy collection is cleared as it is
    converted, so a second run finds nothing. Called from the poll tick and
    ``load_post``, never from a draw callback -- the same place the media-id
    migration runs. A group with no surviving members is dropped, not
    converted: its rect WAS its members' bounds, so it drew nothing at all.

    The rect is the members' bounds plus padding, which is exactly what the old
    draw derived every frame; the colour of a legacy group was a free RGBA
    picker value, so it is carried over as a custom colour rather than being
    forced into the palette.
    """
    groups = getattr(scene, "mixie_moodboard_groups", None)
    frames = _frames(scene)
    if not groups or frames is None:
        return 0

    images = getattr(scene, "mixie_moodboard_images", None) or []
    migrated = 0
    for group_index, group in enumerate(groups):
        members = [
            image
            for image in images
            if getattr(image, "group_index", -1) == group_index
            and not _is_node_owned(image)
        ]
        if not members:
            continue
        frame = create_frame(scene, from_items=members, name=group.name or "")
        if frame is None:
            continue
        # A legacy group's colour came from a full colour picker, so it is
        # almost never one of the palette's pastels. Keep what the user chose.
        try:
            frame.use_custom_color = True
            frame.custom_color = tuple(group.color)[:3]
        except (TypeError, ValueError, AttributeError):
            frame.use_custom_color = False
        if not getattr(group, "visible", True):
            frame.collapsed = True
        frame.locked = bool(getattr(group, "locked", False))
        migrated += 1

    # One-way regardless of how many groups had anything left to convert:
    # the guard above means the collection was non-empty, and leaving it
    # standing would re-run this on every poll tick forever.
    for image in images:
        if getattr(image, "group_index", -1) != -1:
            image.group_index = -1
    groups.clear()
    if migrated:
        logger.info("Migrated %d legacy moodboard group(s) to frames", migrated)
    return migrated
