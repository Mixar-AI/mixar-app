# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""QR pairing code as a panel icon.

Same pattern as ``space_mixie_chat.core.avatar_icon``: rasterize a PNG,
load it through ``bpy.utils.previews`` (preserves alpha on template_icon),
cache by content, and degrade to 0 (caller hides the QR) on any failure.
No Pillow needed — the matrix is rasterized straight into our own PNG
encoder. Generated lazily on first draw, cached until the URL changes.
"""

from __future__ import annotations

import os

import bpy
import bpy.utils.previews

from mixar.config.logging_config import get_logger

from . import qr_encoder, stream_encode

_logger = get_logger(__name__)

_SCALE = 8          # pixels per module
_QUIET = 4          # quiet-zone modules around the code

_pcoll = None
_cached_url: str | None = None
_cached_icon_id = 0


def _rasterize(matrix: list[list[bool]]) -> tuple[bytes, int]:
    n = len(matrix)
    size = (n + 2 * _QUIET) * _SCALE
    dark = b"\x10\x12\x16\xff"
    light = b"\xff\xff\xff\xff"
    light_row = light * size
    rows: list[bytes] = [light_row] * (_QUIET * _SCALE)
    for row in matrix:
        expanded = b"".join(
            (dark if cell else light) * _SCALE for cell in row
        )
        line = light * (_QUIET * _SCALE) + expanded + light * (_QUIET * _SCALE)
        rows.extend([line] * _SCALE)
    rows.extend([light_row] * (_QUIET * _SCALE))
    return b"".join(rows), size


def get_qr_icon_id(url: str) -> int:
    """Preview icon id for *url*'s QR code, or 0 when unavailable."""
    global _pcoll, _cached_url, _cached_icon_id
    if not url:
        return 0
    if url == _cached_url:
        return _cached_icon_id

    try:
        matrix = qr_encoder.encode(url)
        rgba, size = _rasterize(matrix)
        png = stream_encode.encode_png(rgba, size, size, flip_vertical=False)

        cache_dir = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
        png_path = os.path.join(cache_dir, "virtual_camera_qr.png")
        with open(png_path, "wb") as fh:
            fh.write(png)

        # previews entries can't be replaced in place — rebuild the collection
        # (tokens change rarely: server restarts and explicit re-pairing).
        if _pcoll is not None:
            bpy.utils.previews.remove(_pcoll)
        _pcoll = bpy.utils.previews.new()
        preview = _pcoll.load("virtual_camera_qr", png_path, 'IMAGE')
        _cached_url = url
        _cached_icon_id = preview.icon_id
        return _cached_icon_id
    except Exception as exc:
        _logger.warning("virtual_camera: QR icon generation failed: %s", exc)
        _cached_url = url
        _cached_icon_id = 0
        return 0


def clear() -> None:
    global _pcoll, _cached_url, _cached_icon_id
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:
            pass
        _pcoll = None
    _cached_url = None
    _cached_icon_id = 0
