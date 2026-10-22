# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Selected moodboard videos become context FILES, not chat pills.

The agent chat has no video content part on the wire, so a selected movie
tile cannot be mirrored into ``pending_attachments`` like a still. Instead the
same poll tick that reconciles stills mirrors the board's video selection onto
the context-file chips: every currently selected video — a loaded tile, a
clip inside a selected frame, or the result of a selected Video Gen / Video
Upscale node — is attached (``context_folder.core.files.attach_file``,
idempotent) so the agent can sample its frames through
``context_folder.view_video``, and a chip THIS hook created
(``origin == "moodboard"``) is detached once its tile (or node) is deselected —
the same follow-the-selection rule the image pills obey. Chips from the
picker, an OS drop or From Blend (any other ``origin``) are never auto-removed.
"""

from __future__ import annotations

import os

from mixar.config.logging_config import get_logger
from .media_utils import (
    describe_moodboard_media,
    is_video_item,
    selected_exportable_media_entries,
)

_logger = get_logger(__name__)

#: ``MixieContextFile.origin`` of a chip the board selection owns.
MOODBOARD_ORIGIN = "moodboard"


def selected_video_items(scene) -> list:
    """Every selected board video, in board order, without duplicates.

    Three ways a clip counts as selected, matching what the user sees:

    * its own tile is selected (a loaded video);
    * it is the embedded result of a selected Video Gen / Video Upscale node —
      ``node_graph.connect_video_result`` pins such an item's ``selected`` to
      False and a click selects the owning node instead, so only the shared
      ``media_utils.selected_exportable_media`` walk reaches it;
    * it sits inside a selected frame (the same rule stills follow), which
      the shared walk does not cover.
    """
    images_attr = getattr(scene, "mixie_moodboard_images", None)
    if images_attr is None:
        return []
    picked = {
        index for index, item in selected_exportable_media_entries(scene)
        if is_video_item(item)
    }
    frame_ids = {
        frame.frame_id
        for frame in getattr(scene, "mixie_moodboard_frames", ()) or ()
        if getattr(frame, "selected", False) and getattr(frame, "frame_id", "")
    }
    # One board-order walk: indices dedupe (RNA wrappers are rebuilt on every
    # collection access, so identity cannot) and keep the order stable.
    return [
        item for index, item in enumerate(images_attr)
        if is_video_item(item)
        and (index in picked
             or (frame_ids and getattr(item, "frame_id", "") in frame_ids))
    ]


def selected_video_names(scene) -> tuple:
    """Sorted datablock names: part of the poll's selection signature."""
    return tuple(sorted(item.image.name for item in selected_video_items(scene)))


def _stale_moodboard_chips(scene, selected_paths: set, registry) -> list:
    """File ids of board-owned chips whose movie is no longer selected,
    compared by resolved path. A chip this machine cannot resolve is left
    alone: the hook cannot tell what it stood for."""
    stale = []
    for item in scene.mixie_context_files:
        if getattr(item, "origin", "") != MOODBOARD_ORIGIN:
            continue
        try:
            path = os.path.realpath(str(registry.resolve_file(item.file_id)))
        except Exception:  # noqa: BLE001 — file_unknown / file_unavailable
            continue
        if path not in selected_paths:
            stale.append(item.file_id)
    return stale


def sync_selected_videos(scene) -> tuple[int, int]:
    """Mirror the board's video selection onto the context-file chips.

    Returns ``(attached, detached)``: how many chips are NEW (an already
    attached clip counts for nothing) and how many board-owned chips went
    because their tile was deselected. A refused attach (the cap, a hidden
    name, a registry write failure) is logged, not toasted — parity with the
    still sync, which is silent at its cap. Never raises."""
    if not hasattr(scene, "mixie_context_files"):
        return 0, 0
    try:
        from mixar.modules.context_folder.core.files import attach_file, detach_file
        from mixar.modules.context_folder.core.registry import get_registry
    except Exception as exc:  # noqa: BLE001 — the module may be absent in a stripped build
        _logger.debug("context files unavailable: %s", exc)
        return 0, 0
    attached, selected_paths = 0, set()
    for item in selected_video_items(scene):
        try:
            described = describe_moodboard_media(item)
            filepath = described["resolved_filepath"]
            if not filepath or not described.get("source_available"):
                continue  # a moved/deleted movie: nothing to attach
            selected_paths.add(os.path.realpath(filepath))
            result = attach_file(scene, filepath, origin=MOODBOARD_ORIGIN)
        except Exception as exc:  # noqa: BLE001 — one bad clip never stops the sync
            _logger.debug("moodboard video attach failed: %s", exc, exc_info=True)
            continue
        if not result.get("success"):
            _logger.info("moodboard video not attached as context: %s %s",
                         result.get("error"), result.get("error_args") or "")
        elif not result.get("already"):
            attached += 1
    detached = 0
    try:
        stale = _stale_moodboard_chips(scene, selected_paths, get_registry())
    except Exception as exc:  # noqa: BLE001
        _logger.debug("moodboard video detach scan failed: %s", exc, exc_info=True)
        stale = []
    for file_id in stale:
        if detach_file(scene, file_id):
            detached += 1
    return attached, detached
