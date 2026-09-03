# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Typed media helpers for moodboard images and videos.

Blender represents both still images and movies with ``bpy.types.Image``.
Keeping that shared datablock lets video items reuse the moodboard's existing
canvas behavior, while these helpers expose the original movie file needed by
future video-generation upload paths.  Video bytes deliberately remain on
disk: callers can stream ``resolved_filepath`` instead of base64-encoding a
potentially large movie in Blender memory.
"""

from __future__ import annotations

import mimetypes
import os
import stat
import time
from typing import Callable, Literal, TypedDict


MediaType = Literal["IMAGE", "VIDEO"]

# The Video Gen drawer redraws with the canvas pulse (15 fps while a node
# generates), and every draw used to re-stat every selected reference. The
# hint it feeds tolerates sub-second staleness; submission paths re-stat fresh
# via ``fresh=True`` so the authoritative check never trusts the cache.
SOURCE_PROBE_TTL_S = 2.0

_source_probe_cache: dict[str, tuple[float, bool, int]] = {}


def _probe_source(
    resolved_path: str, *, use_cache: bool
) -> tuple[bool, int]:
    """(exists-as-file, size) for *resolved_path* in ONE stat.

    ``isfile`` + ``getsize`` was two syscalls per path per draw; the stat that
    answers availability also carries the size.
    """
    now = time.monotonic()
    if use_cache:
        cached = _source_probe_cache.get(resolved_path)
        if cached is not None and now - cached[0] < SOURCE_PROBE_TTL_S:
            return cached[1], cached[2]
    available = False
    size = 0
    try:
        st = os.stat(resolved_path)
        available = stat.S_ISREG(st.st_mode)
        if available:
            size = st.st_size
    except OSError:
        pass
    if len(_source_probe_cache) > 1024:
        # Bounded churn guard: these are probe results, not identity — losing
        # them only costs a re-stat.
        _source_probe_cache.clear()
    _source_probe_cache[resolved_path] = (now, available, size)
    return available, size


class MoodboardMediaInput(TypedDict):
    """Backend-ready metadata for one moodboard media item."""

    image: object | None
    image_name: str
    media_type: MediaType
    filepath: str
    resolved_filepath: str
    filename: str
    mime_type: str
    file_size_bytes: int
    source_available: bool
    width: int
    height: int
    frame_count: int


class SelectedVideoInputs(TypedDict):
    """Selected moodboard videos and their source-file metadata."""

    count: int
    videos: list[MoodboardMediaInput]
    has_selection: bool
    all_sources_available: bool


class SelectedMediaInputs(TypedDict):
    """Selected still and video references for mixed-media generation."""

    count: int
    images: list[MoodboardMediaInput]
    videos: list[MoodboardMediaInput]
    all_video_sources_available: bool


def is_video_image(image: object | None) -> bool:
    """Return whether *image* is a Blender movie ``Image`` datablock."""
    return image is not None and getattr(image, "source", "") == "MOVIE"


def is_video_item(item: object | None) -> bool:
    """Return whether a moodboard item points at a movie datablock."""
    return item is not None and is_video_image(getattr(item, "image", None))


def is_still_image(image: object | None) -> bool:
    """Return whether *image* is a non-movie Blender image datablock."""
    return image is not None and not is_video_image(image)


def is_still_item(item: object | None) -> bool:
    """Return whether a moodboard item points at a still-image datablock."""
    return item is not None and is_still_image(getattr(item, "image", None))


def media_type_for_image(image: object | None) -> MediaType:
    """Return the stable media discriminator used by queue payload builders."""
    return "VIDEO" if is_video_image(image) else "IMAGE"


def _default_path_resolver(filepath: str) -> str:
    """Resolve Blender ``//`` paths without importing bpy during tests."""
    try:
        import bpy

        resolved = bpy.path.abspath(filepath)
        # Blender returns a string. Restrict this check so test doubles with a
        # synthetic ``__fspath__`` (for example MagicMock) do not masquerade as
        # a usable resolved path.
        if isinstance(resolved, (str, bytes)):
            return os.fspath(resolved)
    except (ImportError, AttributeError, TypeError):
        pass
    return os.path.abspath(filepath)


def describe_moodboard_media(
    item: object,
    *,
    path_resolver: Callable[[str], str] | None = None,
    use_cache: bool = False,
) -> MoodboardMediaInput:
    """Describe one moodboard item for a future upload/submission pipeline.

    The returned ``resolved_filepath`` is the authoritative input for videos.
    ``source_available`` lets a caller fail before queue submission when a
    linked movie has moved or been deleted.  Still images retain the same shape
    so mixed-media selection can be inspected without type guessing.

    ``use_cache`` lets a redraw path reuse the (short-TTL) availability/size
    probe; anything that gates a submission must leave it ``False``.
    """
    image = getattr(item, "image", None)
    media_type = media_type_for_image(image)
    filepath = str(getattr(image, "filepath", "") or "") if image else ""
    resolver = path_resolver or _default_path_resolver

    resolved_filepath = ""
    if filepath:
        try:
            # realpath already returns an absolute, normalized path — a second
            # abspath over it is redundant.
            resolved_filepath = os.path.realpath(resolver(filepath))
        except (OSError, TypeError, ValueError):
            resolved_filepath = ""

    source_available = False
    file_size_bytes = 0
    if resolved_filepath:
        source_available, file_size_bytes = _probe_source(
            resolved_filepath, use_cache=use_cache
        )
        if not source_available:
            file_size_bytes = 0

    filename = os.path.basename(resolved_filepath or filepath)
    guessed_mime, _ = mimetypes.guess_type(filename)
    default_mime = "application/octet-stream"

    size = getattr(image, "size", (0, 0)) if image else (0, 0)
    try:
        width, height = int(size[0]), int(size[1])
    except (IndexError, TypeError, ValueError):
        width, height = 0, 0

    frame_count = 1
    if media_type == "VIDEO":
        try:
            frame_count = max(1, int(getattr(image, "frame_duration", 1)))
        except (TypeError, ValueError):
            frame_count = 1

    return {
        "image": image,
        "image_name": str(getattr(image, "name", "") or "") if image else "",
        "media_type": media_type,
        "filepath": filepath,
        "resolved_filepath": resolved_filepath,
        "filename": filename,
        "mime_type": guessed_mime or default_mime,
        "file_size_bytes": file_size_bytes,
        "source_available": source_available,
        "width": width,
        "height": height,
        "frame_count": frame_count,
    }


def selected_exportable_media(scene) -> list:
    """Media the user has selected, including results owned by selected nodes.

    A generated result is deliberately never ``selected`` itself: its inference
    node owns it and carries the selection, and the canvas hit-tests skip
    ``embedded_node_id`` items so they cannot be picked directly. Any
    selection-driven action that should still reach them has to resolve through
    the owning node — otherwise right-clicking a completed node offers an
    action that can only report "nothing selected".

    Deliberately limited to read-only actions such as export. Editing a result
    in place (crop, rotate, flip) would desynchronise it from the node that
    produced it, so those stay keyed on direct selection.
    """
    owners = {
        str(node.node_id) for node in getattr(scene, "mixie_moodboard_action_nodes", ())
        if node.selected and node.node_id
    }
    return [
        item for item in getattr(scene, "mixie_moodboard_images", ())
        if getattr(item, "image", None)
        and (item.selected or (item.embedded_node_id and item.embedded_node_id in owners))
    ]


def get_selected_moodboard_video_inputs(context=None, *, fresh: bool = False) -> SelectedVideoInputs:
    """Return selected video inputs without loading their bytes into memory.

    ``fresh=True`` re-stats every source; leave it for submit paths. Draw
    callers accept the short-TTL cache.
    """
    if context is None:
        import bpy

        context = bpy.context

    videos: list[MoodboardMediaInput] = []
    scene = getattr(context, "scene", None)
    items = getattr(scene, "mixie_moodboard_images", ()) if scene else ()
    use_cache = not fresh
    for item in items:
        if getattr(item, "selected", False) and is_video_item(item):
            videos.append(describe_moodboard_media(item, use_cache=use_cache))

    return {
        "count": len(videos),
        "videos": videos,
        "has_selection": bool(videos),
        "all_sources_available": all(video["source_available"] for video in videos),
    }


def get_selected_moodboard_media_inputs(
    context=None, *, fresh: bool = False
) -> SelectedMediaInputs:
    """Return selected stills and linked movies without loading video bytes.

    ``fresh=True`` re-stats every source; the submit operator must pass it,
    while the drawer accepts the short-TTL cache (this runs on every canvas
    pulse redraw).
    """
    if context is None:
        import bpy

        context = bpy.context

    images = []
    videos = []
    scene = getattr(context, "scene", None)
    items = getattr(scene, "mixie_moodboard_images", ()) if scene else ()
    use_cache = not fresh
    for item in items:
        if not getattr(item, "selected", False) or getattr(item, "image", None) is None:
            continue
        description = describe_moodboard_media(item, use_cache=use_cache)
        if description["media_type"] == "VIDEO":
            videos.append(description)
        else:
            images.append(description)
    return {
        "count": len(images) + len(videos),
        "images": images,
        "videos": videos,
        "all_video_sources_available": all(
            video["source_available"] for video in videos
        ),
    }
