# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — movie frames as GPU textures.

``bpy.data.images.load`` opens the recording as a ``'MOVIE'`` image.
Blender's image GPU cache holds ONE texture per image and does not follow
a changed movie frame (``gpu.texture.from_image`` just returns whatever is
cached), so decoding frame N from Python is ``gl_free()`` +
``gl_load(frame=N)`` + ``from_image``. That destroys and recreates the
texture, which is the Metal command-buffer churn the moodboard renderer
warns about; when the C++ helper ``Image.mixar_movie_frame_update(frame)``
is present it updates the cached texture in place and we prefer it.

Either way a frame is decoded only when the *frame index* changes, so a
30 Hz tick against a 24 fps movie costs 24 decodes a second, not 30.

The ``GPUTexture`` handed out is re-fetched with ``from_image`` on EVERY
call: it is a cheap non-owning wrapper, and both decode paths (the helper's
fallback branch included) may replace the cached texture, so a wrapper held
across frames could dangle.

Frame rate: Blender's Image RNA exposes the frame count but not the fps,
so it is estimated from the audio track length (``aud``) and snapped to a
standard rate; ``config.VIDEO_FPS_FALLBACK`` covers a silent container.
The audio length is only trusted when it agrees with the video: a trimmed
audio tail would make the fps too high and ``duration_ms`` too short, the
clock would clamp at that ceiling and a mid-table beat could never end
(see ``estimate_fps`` — the runner's stall watchdog is the second net).

``texture_for_ms`` runs inside draw callbacks: every GPU call is guarded
and a failure logs once and degrades to drawing nothing.
"""

import os
from typing import Optional

from mixar.config.logging_config import get_logger

from . import config

logger = get_logger(__name__)

_STANDARD_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 48.0, 50.0, 59.94, 60.0)
_SNAP_TOLERANCE = 0.01  # 1 %: AAC priming/padding shifts the audio length slightly
_FPS_MIN, _FPS_MAX = 5.0, 240.0
# An audio track shorter than this fraction of the video's fallback-rate
# duration is treated as trimmed and ignored.
_AUDIO_DURATION_MIN_RATIO = 0.9
_fallback_warned = False


def _audio_seconds(path: str) -> Optional[float]:
    """Length of the container's audio track, or None."""
    try:
        import aud
        snd = aud.Sound(path)
        samples = int(snd.length)
        sample_rate = float(snd.specs[0])
    except Exception as exc:
        logger.debug("MovieTexture: audio length unavailable for %s: %s", path, exc)
        return None
    if samples <= 0 or sample_rate <= 0:
        return None
    return samples / sample_rate


def _snap_fps(fps: float) -> float:
    nearest = min(_STANDARD_FPS, key=lambda std: abs(fps - std))
    if abs(fps - nearest) <= nearest * _SNAP_TOLERANCE:
        return nearest
    return fps


def _warn_fallback_once(reason: str) -> None:
    """One warning per process; a repeat (the next tour) logs at debug."""
    global _fallback_warned
    level = logger.debug if _fallback_warned else logger.warning
    _fallback_warned = True
    level("MovieTexture: %s; using the fallback rate of %.3f fps",
          reason, config.VIDEO_FPS_FALLBACK)


def estimate_fps(frame_count: int, seconds: Optional[float]) -> float:
    """Frame rate from the frame count and the audio length.

    The audio-derived rate is used only when it is plausible: within
    ``[_FPS_MIN, _FPS_MAX]``, and the audio no shorter than
    ``_AUDIO_DURATION_MIN_RATIO`` of the video's length at the fallback
    rate (``config.VIDEO_FPS_FALLBACK`` is the rate the asset is expected
    to have). A trimmed audio tail would otherwise shrink ``duration_ms``
    below the beat table and stall the tour at the clock's clamp. The
    fallback wins on a mismatch: its duration is never shorter than the
    video, so the table stays reachable.
    """
    fallback = config.VIDEO_FPS_FALLBACK
    if not seconds or seconds <= 0 or frame_count <= 0:
        return fallback
    fps = _snap_fps(frame_count / seconds)
    if not (_FPS_MIN <= fps <= _FPS_MAX):
        # A bogus audio length (silent track, mocked aud) must not produce
        # an absurd rate that races through the movie.
        _warn_fallback_once(f"audio length {seconds:.2f}s implies {fps:.2f} fps "
                            f"for {frame_count} frames")
        return fallback
    video_seconds = frame_count / fallback
    if seconds < video_seconds * _AUDIO_DURATION_MIN_RATIO:
        _warn_fallback_once(f"audio length {seconds:.2f}s is shorter than the "
                            f"video ({video_seconds:.2f}s at {fallback:.3f} fps)")
        return fallback
    return fps


def frame_index_for_ms(ms: int, fps: float, frame_count: int) -> int:
    """1-based frame index for a video position (clamped)."""
    n = int(max(0, ms) / 1000.0 * fps) + 1
    return max(1, min(n, max(1, frame_count)))


class MovieTexture:
    """One movie datablock and its current-frame GPU texture."""

    def __init__(self, path: str):
        import bpy

        if not path or not os.path.isfile(path):
            raise RuntimeError(f"movie not found: {path!r}")
        try:
            img = bpy.data.images.load(path, check_existing=True)
        except Exception as exc:
            raise RuntimeError(f"movie failed to load: {path!r}: {exc}") from exc
        if getattr(img, "source", None) != 'MOVIE':
            raise RuntimeError(f"not a movie: {path!r} (source={img.source!r})")
        # Treat the frames as display-ready bytes. As 'sRGB' Blender uploads
        # an SRGB8_A8 texture, the IMAGE shader samples it LINEAR and writes
        # that straight into the window, which reads as a heavy dark filter.
        # 'Non-Color' keeps the bytes untouched end to end.
        try:
            if img.colorspace_settings.name != 'Non-Color':
                img.colorspace_settings.name = 'Non-Color'
                img.gl_free()
        except Exception as exc:  # noqa: BLE001
            logger.debug("MovieTexture: colorspace set failed: %s", exc)

        self.path = path
        self._img = img
        self.frame_count = max(1, int(img.frame_duration))
        self.width = int(img.size[0])
        self.height = int(img.size[1])
        if self.width <= 0 or self.height <= 0:
            raise RuntimeError(f"movie has no decodable frames: {path!r}")

        self.fps = estimate_fps(self.frame_count, _audio_seconds(path))
        self.duration_ms = int(round(self.frame_count / self.fps * 1000.0))

        self._fast = hasattr(img, "mixar_movie_frame_update")
        self._frame = 0             # currently decoded frame (0 = none)
        self._warned = False
        logger.info("MovieTexture: %s %dx%d %d frames @ %.3f fps (%s ms, %s)",
                    os.path.basename(path), self.width, self.height,
                    self.frame_count, self.fps, self.duration_ms,
                    "in-place" if self._fast else "gl_free/gl_load")

    # -- frames ----------------------------------------------------------

    def frame_for_ms(self, ms: int) -> int:
        return frame_index_for_ms(ms, self.fps, self.frame_count)

    def texture_for_ms(self, ms: int):
        """GPUTexture for the frame at ``ms``; decodes only on a change.

        A failed decode keeps whatever frame the cache holds (logged once)
        and is retried on the next call; the wrapper is always fresh.
        """
        n = self.frame_for_ms(ms)
        if n != self._frame and self._decode(n):
            self._frame = n
        return self._current_texture()

    def _decode(self, n: int) -> bool:
        if self._fast:
            try:
                ok = bool(self._img.mixar_movie_frame_update(frame=n))
            except Exception as exc:
                self._warn_once(f"in-place update of frame {n} failed", exc)
                return False
            if not ok:
                self._warn_once(f"in-place update of frame {n} returned False", None)
            return ok
        try:
            self._img.gl_free()
            error = self._img.gl_load(frame=n)
        except Exception as exc:
            self._warn_once(f"gl_load(frame={n}) failed", exc)
            return False
        if error:
            self._warn_once(f"gl_load(frame={n}) returned {error}", None)
            return False
        return True

    def _current_texture(self):
        """A fresh non-owning wrapper of the image's cached texture."""
        try:
            import gpu
            return gpu.texture.from_image(self._img)
        except Exception as exc:
            # No GPU context (not a draw callback) or the image has no texture.
            self._warn_once("from_image failed", exc)
            return None

    def _warn_once(self, what: str, exc) -> None:
        if self._warned:
            return
        self._warned = True
        if exc is None:
            logger.warning("MovieTexture %s: %s", os.path.basename(self.path), what)
        else:
            logger.warning("MovieTexture %s: %s: %s",
                           os.path.basename(self.path), what, exc)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        """Release the GPU texture; the datablock stays (``check_existing``
        reuses it on the next tour)."""
        self._frame = 0
        img, self._img = self._img, None
        if img is None:
            return
        try:
            img.gl_free()
        except Exception as exc:
            logger.debug("MovieTexture: gl_free failed: %s", exc)


def draw_textured_quad(texture, x: float, y: float, w: float, h: float) -> None:
    """Draw ``texture`` over the rect (region pixels) with alpha blending."""
    if texture is None:
        return
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return

    verts = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    indices = ((0, 1, 2), (0, 2, 3))
    try:
        shader = gpu.shader.from_builtin('IMAGE')
        batch = batch_for_shader(shader, 'TRIS',
                                 {"pos": verts, "texCoord": uvs},
                                 indices=indices)
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_sampler("image", texture)
        batch.draw(shader)
        gpu.state.blend_set('NONE')
    except Exception as exc:
        # No GPU context (not a draw callback) or a stale texture.
        logger.debug("draw_textured_quad failed: %s", exc)
