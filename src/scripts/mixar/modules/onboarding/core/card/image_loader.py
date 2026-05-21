# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card — Image Loader

Lazily loads image assets from ``onboarding/assets/`` into Blender's
``bpy.data.images`` and turns them into ``gpu.types.GPUTexture``
objects we can sample from a draw callback.

Caching: per-path, both the ``bpy.data.images`` entry and the
``GPUTexture`` are cached for the session. ``draw_image_textured``
draws a quad with the cached texture.

Failures (missing file, image load error, GPU texture creation
fail) are logged once at WARNING and then silenced — the renderer
falls back to skipping the image.
"""

import os

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Keyed by absolute file path → GPUTexture. Cleared at addon
# unregister via :func:`reset_cache`.
_texture_cache: dict = {}

# Paths we've already failed to load — don't spam the log every frame.
_failed_paths: set = set()


def _assets_dir() -> str:
    """Directory containing onboarding image assets."""
    here = os.path.dirname(os.path.abspath(__file__))
    # core/card → ../../assets
    return os.path.normpath(os.path.join(here, "..", "..", "assets"))


def _load_texture(asset_name: str):
    """Return a cached ``GPUTexture`` for ``onboarding/assets/<asset_name>``,
    or ``None`` on any failure. Logs the first failure for a given
    asset and stays silent afterwards.
    """
    path = os.path.join(_assets_dir(), asset_name)
    if path in _texture_cache:
        return _texture_cache[path]
    if path in _failed_paths:
        return None

    if not os.path.isfile(path):
        logger.warning("Onboarding image not found: %s", path)
        _failed_paths.add(path)
        return None

    try:
        # ``check_existing=True`` avoids creating duplicates if the
        # path was previously loaded (e.g. across script reloads).
        image = bpy.data.images.load(path, check_existing=True)
    except Exception as exc:
        logger.warning("Onboarding image load failed (%s): %s", path, exc)
        _failed_paths.add(path)
        return None

    try:
        # gpu_load() is required before from_image() can sample,
        # otherwise the underlying buffer may not be populated yet.
        if hasattr(image, "gpu_load"):
            image.gpu_load()
        tex = gpu.texture.from_image(image)
    except Exception as exc:
        logger.warning("Onboarding image GPU upload failed (%s): %s", path, exc)
        _failed_paths.add(path)
        return None

    _texture_cache[path] = tex
    logger.debug("Onboarding image loaded: %s", path)
    return tex


def draw_image_textured(asset_name: str, x: float, y: float,
                         w: float, h: float) -> bool:
    """Draw the image at ``(x, y)`` with size ``(w, h)`` using the
    GPU's ``IMAGE`` builtin shader. Returns True on success.

    Returns False (silently — caller can fall back) if the image
    couldn't be loaded.
    """
    tex = _load_texture(asset_name)
    if tex is None:
        return False

    verts = (
        (x,     y),
        (x + w, y),
        (x + w, y + h),
        (x,     y + h),
    )
    uvs = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    )
    indices = ((0, 1, 2), (0, 2, 3))

    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": verts, "texCoord": uvs},
        indices=indices,
    )

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_sampler("image", tex)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    return True


def reset_cache() -> None:
    """Drop every cached texture. Called from addon unregister so
    we don't hold GPU resources after Mixar disables itself."""
    _texture_cache.clear()
    _failed_paths.clear()
