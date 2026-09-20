# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Zen header's shading-options popover is a glass chip, not a bare box.

QA reported the "render settings menu" beside the shading strip as broken:
the popover was drawn on the bare cluster, so the native Popover widget
painted a square themed box with an orphan chevron next to the glass
capsule. It now follows the guides chip recipe — its own Zen surface, a
one-button aligned row and an icon — and the shared painter accepts
Popover buttons as glass cells.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    ROOT / "src/scripts/mixar/modules/workflow/ui/headers/view3d_header_filter.py"
).read_text(encoding="utf-8")
WIDGETS = (
    ROOT / "src/source/blender/editors/interface/interface_widgets.cc"
).read_text(encoding="utf-8")


def _header_draw():
    return HEADER.split("def _patched_header_draw", 1)[1].split(
        "def _patched_tool_header_draw", 1
    )[0]


def test_the_popover_sits_on_its_own_zen_surface_beside_the_strip():
    header = _header_draw()
    assert 'options = cluster.mixar_surface(theme="ZEN").row(align=True)' in header
    assert 'options.popover(panel="VIEW3D_PT_shading", text="", icon="PREFERENCES")' in header
    # Beside the enum capsule, after the guides chip, never inside `row`.
    assert 'row.popover(' not in header
    assert 'cluster.popover(' not in header
    assert header.index("mixar.zen_toggle_guides") < header.index("options = cluster.mixar_surface")


def test_the_glass_painter_paints_popover_icon_chips():
    cell = WIDGETS.split("static bool zen_glass_cell(const Button *but)\n{", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "ButtonType::Popover" in cell
    # The emboss draw path must route a glass Popover to the Zen painter
    # instead of the native menu widget, with the strip's icon colour.
    dispatch = WIDGETS[WIDGETS.index("bool native_text = true;"):]
    dispatch = dispatch[: dispatch.index("else if (wt->custom)")]
    assert "ELEM(but->type, ButtonType::Row, ButtonType::Popover) && zen_glass_cell(but)" in dispatch
    assert "wcol_radio" in dispatch
