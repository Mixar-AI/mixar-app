# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport frame encoding for the phone stream.

Runs on a worker thread (never the main thread). JPEG via Pillow when the
embedded Python has it; otherwise a dependency-free PNG path (zlib is C-speed,
and browsers decode either transparently from a binary WS frame).
"""

from __future__ import annotations

import struct
import zlib
from types import ModuleType

try:
    from PIL import Image  # type: ignore

    # Guard against test environments that stub PIL with a MagicMock
    # (mixar.modules.testing.mock_bpy) — same check as the moodboard tests.
    _HAS_PIL = isinstance(Image, ModuleType)
except ImportError:
    _HAS_PIL = False


def has_jpeg_support() -> bool:
    return _HAS_PIL


def encode_frame(rgba: bytes, width: int, height: int, *,
                 jpeg_quality: int = 68, flip_vertical: bool = True) -> bytes:
    """Encode raw RGBA8 pixels to JPEG (preferred) or PNG bytes.

    GPU reads are bottom-up, so ``flip_vertical`` defaults to True.
    """
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"buffer size {len(rgba)} != {expected} for {width}x{height}")
    if _HAS_PIL:
        return _encode_jpeg(rgba, width, height, jpeg_quality, flip_vertical)
    return encode_png(rgba, width, height, flip_vertical=flip_vertical)


def _encode_jpeg(rgba: bytes, width: int, height: int,
                 quality: int, flip_vertical: bool) -> bytes:
    import io

    img = Image.frombuffer("RGBA", (width, height), rgba, "raw", "RGBA", 0, 1)
    if flip_vertical:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()


def encode_png(rgba: bytes, width: int, height: int, *,
               flip_vertical: bool = True, compress_level: int = 1) -> bytes:
    """Minimal valid RGBA PNG. Row filter 0 everywhere; speed over size."""
    stride = width * 4
    rows = range(height - 1, -1, -1) if flip_vertical else range(height)
    raw = b"".join(
        b"\x00" + rgba[y * stride:(y + 1) * stride] for y in rows
    )
    compressed = zlib.compress(raw, compress_level)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack("!I", len(body)) + tag + body
            + struct.pack("!I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
