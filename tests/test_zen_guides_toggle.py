# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen Mode header control: the grids + relationship-lines toggle chip.

The chip sits beside the floating Wireframe / Solid / Material Preview /
Rendered strip and flips floor grid, axes, ortho grid, relationship
lines, and object extras (the light / camera / empty helpers) together.
Pressed state mirrors whether any of those guides are visible. Only Zen
Mode draws this header at all.
"""

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.workflow.core import viewport_guides

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "src/scripts/mixar/modules/workflow"

CORE = (WORKFLOW / "core/viewport_guides.py").read_text(encoding="utf-8")
OPS = (WORKFLOW / "ui/operators/zen_guides_ops.py").read_text(encoding="utf-8")
HEADER = (WORKFLOW / "ui/headers/view3d_header_filter.py").read_text(encoding="utf-8")


def _space(floor=True, x=True, y=True, ortho=True, relationship=True, extras=True):
    return SimpleNamespace(
        overlay=SimpleNamespace(
            show_floor=floor,
            show_axis_x=x,
            show_axis_y=y,
            show_ortho_grid=ortho,
            show_relationship_lines=relationship,
            show_extras=extras,
        )
    )


def _flags(space):
    return (
        space.overlay.show_floor,
        space.overlay.show_axis_x,
        space.overlay.show_axis_y,
        space.overlay.show_ortho_grid,
        space.overlay.show_relationship_lines,
        space.overlay.show_extras,
    )


# -------------------------------------------------------------------------
# core/viewport_guides.py


def test_guides_shown_is_true_when_floor_or_relationship_is_on():
    assert viewport_guides.guides_shown(_space(floor=True, relationship=False)) is True
    assert viewport_guides.guides_shown(_space(floor=False, relationship=True)) is True
    assert viewport_guides.guides_shown(_space(floor=False, relationship=False)) is False
    assert viewport_guides.guides_shown(SimpleNamespace(overlay=None)) is False
    assert viewport_guides.guides_shown(SimpleNamespace()) is False


def test_toggle_guides_hides_grid_relationship_and_extras_together():
    # Extras is what draws lights, cameras and empties: hiding the guides
    # has to take those helpers with it, or the "clean canvas" click leaves
    # a camera wireframe and a light gizmo behind.
    space = _space(True, True, True, True, True, True)
    assert viewport_guides.toggle_guides(space) is False
    assert _flags(space) == (False, False, False, False, False, False)
    assert viewport_guides.toggle_guides(space) is True
    assert _flags(space) == (True, True, True, True, True, True)


def test_toggle_guides_resyncs_a_mixed_overlay_state():
    # Zen entry forces relationship lines off while the floor may stay on;
    # one click must settle every flag, never leave the chip disagreeing
    # with what is drawn.
    space = _space(
        floor=True, x=True, y=False, ortho=True, relationship=False, extras=True
    )
    assert viewport_guides.toggle_guides(space) is False
    assert _flags(space) == (False, False, False, False, False, False)


def test_toggle_guides_tolerates_partial_overlay_rna():
    space = SimpleNamespace(
        overlay=SimpleNamespace(show_floor=True, show_relationship_lines=True)
    )
    assert viewport_guides.toggle_guides(space) is False
    assert space.overlay.show_floor is False
    assert space.overlay.show_relationship_lines is False


def test_toggle_guides_without_an_overlay_is_a_no_op():
    assert viewport_guides.toggle_guides(SimpleNamespace(overlay=None)) is False


# -------------------------------------------------------------------------
# ui/operators/zen_guides_ops.py


def test_the_operator_is_registered_view_state_with_no_undo():
    assert 'bl_idname = "mixar.zen_toggle_guides"' in OPS
    assert 'bl_label = "Toggle Grid & Relationship Lines"' in OPS
    assert 'bl_options = {"REGISTER"}' in OPS
    assert "UNDO" not in OPS
    assert "MIXAR_OT_zen_toggle_guides" in OPS.split("classes = (", 1)[1]


def test_the_operator_needs_a_3d_view_and_flips_through_core():
    assert '_view3d_space(context)' in OPS
    assert '== "VIEW_3D"' in OPS
    assert "toggle_guides(space)" in OPS
    assert "area.tag_redraw()" in OPS


# -------------------------------------------------------------------------
# ui/headers/view3d_header_filter.py


def test_guides_remain_in_the_native_shading_popover_in_zen_only():
    draw = HEADER.split("def _draw_zen_guides", 1)[1].split("def _patched_tool_header_draw", 1)[0]
    assert "if _is_basic_workspace(context):" in draw
    assert '"mixar.zen_toggle_guides"' in draw
    assert "viewport_guides.guides_shown(context.space_data)" in draw
    assert "shading_panel.append(_draw_zen_guides)" in HEADER
    assert "shading_panel.remove(_draw_zen_guides)" in HEADER


def test_the_glass_painter_accepts_a_standalone_icon_chip():
    # The chip is ButtonType::But, not an expanded enum cell: without this
    # the Zen painter skips it and the native Exec widget draws a square
    # themed box beside the strip's glass.
    widgets = (
        ROOT / "src/source/blender/editors/interface/interface_widgets.cc"
    ).read_text(encoding="utf-8")
    # Split on the definition, not the forward declaration above it.
    cell = widgets.split("static bool zen_glass_cell(const Button *but)\n{", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "ELEM(but->type, ButtonType::Row, ButtonType::But, ButtonType::Popover)" in cell
    # Still narrow: Zen theme, no Mixar component, icon-only, aligned group.
    assert "but->mixar_style.theme != MixarTheme::Zen || but->alignnr == 0" in cell
    assert "but->mixar_style.component != MixarComponent::None" in cell
    assert "but->icon != ICON_NONE" in cell
    assert "but->drawstr.empty()" in cell


def test_guide_flag_list_covers_floor_axes_ortho_relationship_and_extras():
    assert '"show_floor"' in CORE
    assert '"show_axis_x"' in CORE
    assert '"show_axis_y"' in CORE
    assert '"show_ortho_grid"' in CORE
    assert '"show_relationship_lines"' in CORE
    assert '"show_extras"' in CORE


def test_a_glass_chip_takes_the_shading_strips_icon_colours():
    # `Exec` themes from `wcol_tool`, whose `text_sel` is near-black (it is
    # meant to sit on a filled accent box). `widget_state` moves `text_sel`
    # into `text` on select and the glass branch drops the inner fill, so
    # without this the pressed chip painted a black glyph on the selected
    # wash while the `Row` cell beside it painted white.
    widgets = (
        ROOT / "src/source/blender/editors/interface/interface_widgets.cc"
    ).read_text(encoding="utf-8")
    exec_fn = widgets.split("static void widget_roundbut_exec", 1)[1].split(
        "\nstatic ", 1
    )[0]
    glass = exec_fn.split("if (!overlay && zen_glass_cell(but))", 1)[1]
    assert "tui.wcol_radio" in glass
    assert "chip_selected ? radio.text_sel : radio.text" in glass
    # The transform trio shares this painter and keeps its own colours.
    assert "if (!zen_toolbar_tool(but))" in glass
    assert glass.index("if (!zen_toolbar_tool(but))") < glass.index("tui.wcol_radio")
