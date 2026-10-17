# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame sampling from a folder video, for the agent to look at.

The folder side only: the path must resolve inside the attached root, be a
video by suffix and stay under the size cap. The decode → time-mapping → JPEG
work is the shared ``common/utils/video_frames.py`` sampler (also behind
``moodboard.view_video``); its ``VideoFrameError`` codes
(``video_decoder_unavailable``, ``invalid_range``, ``unreadable_video``) are
re-raised unchanged as ``ContextFolderError``.

Thread model: like the rest of the reader this runs on the
``MixarContextFolderRPC`` worker thread, never on Blender's main thread; the
sampler never touches ``bpy``.
"""

from ...common.utils.video_frames import (  # noqa: F401 — test hooks re-exported
    VideoFrameError,
    reset_decoder_for_tests,
    sample_frames,
    set_decoder_for_tests,
)
from ..constants import (
    DEFAULT_VIDEO_FRAME_DIM,
    DEFAULT_VIDEO_FRAMES,
    KIND_VIDEO,
    MAX_VIDEO_FRAME_DIM,
    MAX_VIDEO_FRAMES,
    MAX_VIDEO_SOURCE_BYTES,
)
from .errors import ContextFolderError
from .paths import existing_file, file_kind, normalize_relative_path


def sample_video(root, path, start_s=None, end_s=None, count=DEFAULT_VIDEO_FRAMES,
                 max_dim=DEFAULT_VIDEO_FRAME_DIM) -> dict:
    """Up to ``MAX_VIDEO_FRAMES`` JPEG frames spread over a time range of a folder video."""
    relative = normalize_relative_path(path)
    target = existing_file(root, relative)
    if file_kind(relative) != KIND_VIDEO:
        raise ContextFolderError("not_video", "That file is not a video")
    if target.stat().st_size > MAX_VIDEO_SOURCE_BYTES:
        raise ContextFolderError("file_too_large", "That video is too large to sample")
    try:
        sample = sample_frames(
            str(target), start_s=start_s, end_s=end_s, count=count, max_dim=max_dim,
            max_count=MAX_VIDEO_FRAMES, max_frame_dim=MAX_VIDEO_FRAME_DIM,
        )
    except VideoFrameError as exc:
        raise ContextFolderError(exc.code, exc.message) from exc
    return {"success": True, "path": relative, **sample}
