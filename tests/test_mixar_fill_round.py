# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opaque Mixar fills must replace dest alpha on frost windows.

Widget roundboxes dest-over with ``GPU_BLEND_ALPHA``. On WGL that can leave
dest A at the 0.20 frost wash, so DWM composites dark chips as invisible.
``mixar_fill_round`` is the shared primitive the island chips and tabs use.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "src/source/blender/editors/interface/mixar/text.cc").read_text(
    encoding="utf-8"
)
DRAW = (ROOT / "src/source/blender/editors/space_agent_bubble/agent_ui_draw_primitives.hh").read_text(
    encoding="utf-8"
)
CONTROLS = (
    ROOT / "src/source/blender/editors/space_agent_bubble/agent_ui_controls_paint.cc"
).read_text(encoding="utf-8")
COMPONENTS = (ROOT / "src/source/blender/editors/interface/mixar/components.cc").read_text(
    encoding="utf-8"
)


def test_fill_round_replaces_dest_alpha_for_opaque_chrome():
    assert "color[0] * color[3]" in TEXT
    assert "GPU_BLEND_NONE" in TEXT
    assert "GPU_BLEND_ALPHA_PREMULT" in TEXT
    assert "draw_roundbox_4fv" not in TEXT
    assert "draw_roundbox_corner_set(CNR_ALL)" in TEXT
    assert "constexpr int ARC_MAX = 32" in TEXT
    assert "const float aa = 0.5f" in TEXT
    assert "GPU_PRIM_TRI_STRIP" in TEXT


def test_island_painters_use_the_shared_fill():
    assert "ui::mixar_fill_round(*rect, radius, col);" in DRAW
    assert "ui::mixar_fill_round(*rect, radius, color);" in CONTROLS


def test_component_outline_sets_roundbox_corners():
    assert "draw_roundbox_corner_set(CNR_ALL);" in COMPONENTS
    assert "draw_roundbox_4fv(" in COMPONENTS
