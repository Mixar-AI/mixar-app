# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native viewport geometry and secret masking use physical, not logical pixels."""

import base64
from contextlib import nullcontext
import io
from types import SimpleNamespace

from PIL import Image
import pytest

from mixar.modules.common.ui_control.core import input as native_input, observe


def test_transparent_zen_header_only_occludes_drawn_controls(monkeypatch):
    header = SimpleNamespace(type="TOOL_HEADER", width=100, height=80,
                             as_pointer=lambda: 7)
    area = SimpleNamespace(type="VIEW_3D", height=100, regions=[header])
    item = {"rect": [0, 0, 100, 100], "region_type": "WINDOW", "_area": area,
            "_win": SimpleNamespace(as_pointer=lambda: 1)}
    monkeypatch.setattr(observe, "widgets", lambda: [])
    assert native_input.point(item) == (50, 50)
    monkeypatch.setattr(observe, "widgets", lambda: [{"r": 7, "rect": [40, 0, 100, 100]}])
    assert native_input.point(item) == (20, 50)


def test_retina_secret_mask_uses_widget_pixels_without_double_scaling(monkeypatch):
    from mixar.modules.common.render_coordinator import core as renders
    monkeypatch.setattr(renders, "busy", lambda: False)

    def capture(filepath):
        Image.new("RGB", (100, 100), "red").save(filepath)
        return True

    win = SimpleNamespace(width=50, height=50, as_pointer=lambda: 1, mixar_ui_capture=capture)
    monkeypatch.setattr(observe, "bpy", SimpleNamespace(
        app=SimpleNamespace(is_job_running=lambda _: False),
        context=SimpleNamespace(window_manager=SimpleNamespace(mixar_window_resizing=False),
                                temp_override=lambda **kwargs: nullcontext())))
    block, frame = observe.image(win, [{"secret": True, "w": 1, "rect": [10, 10, 30, 30]}])
    with Image.open(io.BytesIO(base64.b64decode(block["data"]))) as image:
        assert image.getpixel((20, 80)) == (0, 0, 0)
        assert image.getpixel((40, 60)) == (255, 0, 0)
    assert frame["window_width"] == 100 and frame["window_height"] == 100


@pytest.mark.parametrize("start,end,blocked", [
    ((0, 50), (100, 50), True),  # Both endpoints clear, but crosses the panel.
    ((0, 10), (100, 10), False),
    ((50, 0), (50, 100), True),
    ((0, 0), (20, 20), False),
    ((50, 50), (50, 50), True),
])
def test_gesture_path_cannot_cross_an_occluding_panel(start, end, blocked):
    assert native_input.segment_intersects(start, end, (40, 40, 60, 60)) is blocked
