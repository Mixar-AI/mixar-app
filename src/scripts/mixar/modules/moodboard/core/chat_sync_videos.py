# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Selected moodboard videos become context FILES, not chat pills.

The agent chat has no video content part on the wire, so a selected movie
tile cannot be mirrored into ``pending_attachments`` like a still. Instead the
same poll tick that reconciles stills attaches every currently selected video
as a context file (``context_folder.core.files.attach_file``, idempotent), so
the agent can sample its frames through ``context_folder.view_video``.

Deselecting NEVER detaches: a context file outlives the turn by design — the
agent may still be reading it after the user moves on to select something
else — so the chip's × is the only removal path.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger
from .media_utils import describe_moodboard_media, is_video_item

_logger = get_logger(__name__)


def selected_video_items(scene) -> list:
    """Every selected board item that points at a movie datablock, including
    the movies inside a selected frame (the same rule stills follow)."""
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return []
    frame_ids = {
        frame.frame_id
        for frame in getattr(scene, "mixie_moodboard_frames", ()) or ()
        if getattr(frame, "selected", False) and getattr(frame, "frame_id", "")
    }
    return [
        item for item in images_attr
        if is_video_item(item)
        and (getattr(item, "selected", False)
             or (frame_ids and getattr(item, "frame_id", "") in frame_ids))
    ]


def selected_video_names(scene) -> tuple:
    """Sorted datablock names: part of the poll's selection signature."""
    return tuple(sorted(item.image.name for item in selected_video_items(scene)))


def attach_selected_videos(scene) -> int:
    """Attach each selected video's file as a context file; returns how many
    were NEW (an already attached clip counts for nothing). Never raises."""
    attached = 0
    if not hasattr(scene, "mixie_context_files"):
        return 0
    try:
        from mixar.modules.context_folder.core.files import attach_file
    except Exception as exc:  # noqa: BLE001 — the module may be absent in a stripped build
        _logger.debug("context files unavailable: %s", exc)
        return 0
    for item in selected_video_items(scene):
        try:
            described = describe_moodboard_media(item)
            filepath = described["resolved_filepath"]
            if not filepath or not described.get("source_available"):
                continue  # a moved/deleted movie: nothing to attach
            result = attach_file(scene, filepath, origin="moodboard")
        except Exception as exc:  # noqa: BLE001 — one bad clip never stops the sync
            _logger.debug("moodboard video attach failed: %s", exc, exc_info=True)
            continue
        if result.get("success") and not result.get("already"):
            attached += 1
    return attached
