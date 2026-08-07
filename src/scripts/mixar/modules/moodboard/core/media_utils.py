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
from typing import Callable, Literal, TypedDict


MediaType = Literal["IMAGE", "VIDEO"]


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
) -> MoodboardMediaInput:
    """Describe one moodboard item for a future upload/submission pipeline.

    The returned ``resolved_filepath`` is the authoritative input for videos.
    ``source_available`` lets a caller fail before queue submission when a
    linked movie has moved or been deleted.  Still images retain the same shape
    so mixed-media selection can be inspected without type guessing.
    """
    image = getattr(item, "image", None)
    media_type = media_type_for_image(image)
    filepath = str(getattr(image, "filepath", "") or "") if image else ""
    resolver = path_resolver or _default_path_resolver

    resolved_filepath = ""
    if filepath:
        try:
            resolved_filepath = os.path.abspath(os.path.realpath(resolver(filepath)))
        except (OSError, TypeError, ValueError):
            resolved_filepath = ""

    source_available = bool(resolved_filepath and os.path.isfile(resolved_filepath))
    file_size_bytes = 0
    if source_available:
        try:
            file_size_bytes = os.path.getsize(resolved_filepath)
        except OSError:
            source_available = False

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


def get_selected_moodboard_video_inputs(context=None) -> SelectedVideoInputs:
    """Return selected video inputs without loading their bytes into memory."""
    if context is None:
        import bpy

        context = bpy.context

    videos: list[MoodboardMediaInput] = []
    scene = getattr(context, "scene", None)
    items = getattr(scene, "mixie_moodboard_images", ()) if scene else ()
    for item in items:
        if getattr(item, "selected", False) and is_video_item(item):
            videos.append(describe_moodboard_media(item))

    return {
        "count": len(videos),
        "videos": videos,
        "has_selection": bool(videos),
        "all_sources_available": all(video["source_available"] for video in videos),
    }


def get_selected_moodboard_media_inputs(context=None) -> SelectedMediaInputs:
    """Return selected stills and linked movies without loading video bytes."""
    if context is None:
        import bpy

        context = bpy.context

    images = []
    videos = []
    scene = getattr(context, "scene", None)
    items = getattr(scene, "mixie_moodboard_images", ()) if scene else ()
    for item in items:
        if not getattr(item, "selected", False) or getattr(item, "image", None) is None:
            continue
        description = describe_moodboard_media(item)
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
