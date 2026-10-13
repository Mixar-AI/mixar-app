# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sample a video file as a handful of JPEG frames for the agent to look at.

Shared by every feature that lets the agent "watch" a clip — context-folder
videos (``context_folder.view_video``) and Moodboard videos
(``moodboard.view_video``). Callers decide WHICH file may be read; this module
only turns an already-authorised path into frames.

Thread model: worker-thread safe. The decoder, ``imbuf.mixar_movie_frames``
(C++, FFmpeg in-process — ``src/source/blender/python/generic/
imbuf_mixar_movie.cc``), is a pure function over a file path: it never touches
``bpy`` data or Main and releases the GIL while decoding, so a long clip never
stalls the UI and no main-thread hop is needed. Nothing here imports ``bpy``.

Two decoder calls per request: a cheap probe of frame 0 at a tiny size to
learn ``frame_count``/``fps`` (needed to turn seconds into frame indices),
then the real sample. Frames come back as RGBA bytes and leave as JPEGs.
"""

import base64
import io

# Longest edge of the metadata probe frame; decoded then discarded.
_PROBE_DIM = 64
_UNSET = object()
_DECODER_OVERRIDE = _UNSET


class VideoFrameError(Exception):
    """Expected failure with a stable public code and a path-free message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def set_decoder_for_tests(fn) -> None:
    """Inject a fake decoder (``None`` = this build has none)."""
    global _DECODER_OVERRIDE
    _DECODER_OVERRIDE = fn


def reset_decoder_for_tests() -> None:
    global _DECODER_OVERRIDE
    _DECODER_OVERRIDE = _UNSET


def _decoder():
    if _DECODER_OVERRIDE is not _UNSET:
        return _DECODER_OVERRIDE
    try:
        import imbuf  # Blender's built-in module; absent outside the app.
    except ImportError:
        return None
    return getattr(imbuf, "mixar_movie_frames", None)


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _seconds(value, default: float, high: float) -> float:
    if value is None or value == "":
        return default
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise VideoFrameError("invalid_range", "start_s and end_s must be numbers of seconds") from exc
    if seconds != seconds:  # NaN
        raise VideoFrameError("invalid_range", "start_s and end_s must be numbers of seconds")
    return max(0.0, min(high, seconds))


def frame_indices(start_s, end_s, count: int, frame_count: int, fps: float) -> list:
    """Evenly spaced frame positions over [start, end]; the midpoint for one."""
    duration = frame_count / fps
    start = _seconds(start_s, 0.0, duration)
    end = _seconds(end_s, duration, duration)
    if start >= end:
        raise VideoFrameError("invalid_range", "start_s must be before end_s and within the clip")
    if count == 1:
        times = [(start + end) / 2.0]
    else:
        times = [start + i * (end - start) / (count - 1) for i in range(count)]
    indices = []
    for t in times:
        index = min(frame_count - 1, int(round(t * fps)))
        if index not in indices:
            indices.append(index)
    return indices


def _jpeg_base64(width: int, height: int, rgba: bytes) -> str:
    from PIL import Image

    image = Image.frombytes("RGBA", (width, height), rgba).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def sample_frames(filepath, *, start_s=None, end_s=None, count=6, max_dim=768,
                  max_count=8, max_frame_dim=1024) -> dict:
    """Up to ``max_count`` JPEG frames spread evenly over ``[start_s, end_s]``.

    ``count`` and ``max_dim`` are clamped (``count`` to ``[1, max_count]``,
    ``max_dim`` to ``[64, max_frame_dim]``; a non-number falls back to the
    default). The whole clip is sampled when the range is omitted; one frame
    is the midpoint. Frames are fitted to ``max_dim`` and never upscaled.

    Raises ``VideoFrameError`` with ``video_decoder_unavailable`` (this build
    has no decoder), ``invalid_range`` (``start_s`` ≥ ``end_s``, outside the
    clip, or not numbers) or ``unreadable_video`` (decoder failure, or no
    frame decoded). Messages never contain the path.
    """
    decode = _decoder()
    if decode is None:
        raise VideoFrameError(
            "video_decoder_unavailable",
            "This Mixar build cannot decode video; update Mixar",
        )
    count = _clamp_int(count, min(6, max_count), 1, max_count)
    max_dim = _clamp_int(max_dim, min(768, max_frame_dim), 64, max_frame_dim)
    filepath = str(filepath)
    try:
        frame_count, fps, width, height, _probe = decode(filepath, [0], _PROBE_DIM)
        frame_count, fps = int(frame_count), float(fps)
        if frame_count < 1 or fps <= 0:
            raise ValueError("no frames")
        indices = frame_indices(start_s, end_s, count, frame_count, fps)
        _, _, _, _, decoded = decode(filepath, indices, max_dim)
        frames = [
            {
                "t_s": round(index / fps, 3),
                "frame_index": int(index),
                "mime": "image/jpeg",
                "image_base64": _jpeg_base64(int(w), int(h), rgba),
            }
            for index, w, h, rgba in sorted(decoded, key=lambda frame: frame[0])
        ]
    except VideoFrameError:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        raise VideoFrameError("unreadable_video", "That video could not be decoded") from exc
    if not frames:
        raise VideoFrameError("unreadable_video", "That video could not be decoded")
    return {
        "frame_count": frame_count,
        "fps": fps,
        "duration_s": round(frame_count / fps, 3),
        "width": int(width),
        "height": int(height),
        "frames": frames,
    }
