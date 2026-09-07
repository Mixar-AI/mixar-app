# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The offscreen scene render encodes its PNG without touching ``bpy.data``.

``_service_pending`` runs inside a VIEW_3D POST_PIXEL draw callback; the
encoder it calls used to create, save and remove a ``bpy.data.images``
datablock there — an ID free mid-draw is a Blender crash, not an exception.
The encoder is now pure Python; these tests pin that and its correctness.
"""

import io
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/scene_render_ops.py"


def _module():
    for dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
        sys.modules.setdefault(dep, MagicMock(name=dep))
    from mixar.modules.space_mixie_chat.ui.operators import scene_render_ops

    return scene_render_ops


def test_png_round_trips_pixels_and_flips_gl_rows():
    PIL = pytest.importorskip("PIL.Image")
    ops = _module()
    w, h = 3, 2
    # GL order: row 0 is the BOTTOM of the image.
    bottom = bytes([255, 0, 0, 255] * w)   # red
    top = bytes([0, 0, 255, 255] * w)      # blue
    png = ops.encode_rgba_png(bottom + top, w, h)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    img = PIL.open(io.BytesIO(png))
    assert img.size == (w, h) and img.mode == "RGBA"
    assert img.getpixel((0, 0)) == (0, 0, 255, 255)      # top row is blue
    assert img.getpixel((0, h - 1)) == (255, 0, 0, 255)  # bottom row is red


def test_png_rejects_a_short_buffer():
    ops = _module()
    with pytest.raises(ValueError):
        ops.encode_rgba_png(b"\x00" * 7, 2, 1)


def test_buffer_encoder_uses_no_bpy_data():
    ops = _module()
    src = OPS.read_text()
    start = src.index("def _encode_buffer_png")
    end = src.index("def _draw_scene_offscreen", start)
    block = src[start:end]
    # Strip the docstring — it names the old datablock round trip on purpose.
    code = block.split('"""')[-1]
    assert not re.search(r"bpy\.data\.", code)
    assert "images.new" not in code and "images.remove" not in code
    assert "tempfile" not in src  # no temp-file round trip either

    class _Buf(list):
        dimensions = 0

    buf = _Buf([10, 20, 30, 255] * 4)
    b64 = ops._encode_buffer_png(buf, 2, 2)
    assert isinstance(b64, str) and len(b64) > 0
    assert buf.dimensions == 16


def test_service_pending_is_only_reached_from_a_draw_callback():
    # Documentation guard: the deferred path must stay the fallback and the
    # draw callback must keep every bpy.data mutation out of its reach.
    src = OPS.read_text()
    assert 'draw_handler_add(\n            _service_pending, (), "WINDOW", "POST_PIXEL"' in src
    pending = src[src.index("def _service_pending"): src.index("def _ensure_draw_handler")]
    assert not re.search(r"bpy\.data\.\w+\.(new|remove)\(", pending)
