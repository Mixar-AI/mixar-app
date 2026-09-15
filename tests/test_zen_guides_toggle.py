# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen Mode header control: the grids + relationship-lines toggle chip.

The chip sits beside the floating Wireframe / Solid / Material Preview /
Rendered strip and flips floor grid, axes, ortho grid, and relationship
lines together. Pressed state mirrors whether any of those guides are
visible. Texturing keeps the shared shading strip without this chip.
"""

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.workflow.core import viewport_guides

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "src/scripts/mixar/modules/workflow"

CORE = (WORKFLOW / "core/viewport_guides.py").read_text(encoding="utf-8")
OPS = (WORKFLOW / "ui/operators/zen_guides_ops.py").read_text(encoding="utf-8")
HEADER = (WORKFLOW / "ui/headers/view3d_header_filter.py").read_text(encoding="utf-8")


def _space(floor=True, x=True, y=True, ortho=True, relationship=True):
    return SimpleNamespace(
        overlay=SimpleNamespace(
            show_floor=floor,
            show_axis_x=x,
            show_axis_y=y,
            show_ortho_grid=ortho,
            show_relationship_lines=relationship,
        )
    )


# -------------------------------------------------------------------------
# core/viewport_guides.py


def test_guides_shown_is_true_when_floor_or_relationship_is_on():
    assert viewport_guides.guides_shown(_space(floor=True, relationship=False)) is True
    assert viewport_guides.guides_shown(_space(floor=False, relationship=True)) is True
    assert viewport_guides.guides_shown(_space(floor=False, relationship=False)) is False
    assert viewport_guides.guides_shown(SimpleNamespace(overlay=None)) is False
    assert viewport_guides.guides_shown(SimpleNamespace()) is False


def test_toggle_guides_hides_grid_and_relationship_together():
    space = _space(True, True, True, True, True)
    assert viewport_guides.toggle_guides(space) is False
    assert (
        space.overlay.show_floor,
        space.overlay.show_axis_x,
        space.overlay.show_axis_y,
        space.overlay.show_ortho_grid,
        space.overlay.show_relationship_lines,
    ) == (False, False, False, False, False)
    assert viewport_guides.toggle_guides(space) is True
    assert (
        space.overlay.show_floor,
        space.overlay.show_axis_x,
        space.overlay.show_axis_y,
        space.overlay.show_ortho_grid,
        space.overlay.show_relationship_lines,
    ) == (True, True, True, True, True)


def test_toggle_guides_resyncs_a_mixed_overlay_state():
    # Zen entry forces relationship lines off while the floor may stay on;
    # one click must settle every flag, never leave the chip disagreeing
    # with what is drawn.
    space = _space(floor=True, x=True, y=False, ortho=True, relationship=False)
    assert viewport_guides.toggle_guides(space) is False
    assert (
        space.overlay.show_floor,
        space.overlay.show_axis_x,
        space.overlay.show_axis_y,
        space.overlay.show_ortho_grid,
        space.overlay.show_relationship_lines,
    ) == (False, False, False, False, False)


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


def test_the_chip_sits_beside_the_zen_shading_strip_only():
    header = HEADER.split("def _patched_header_draw", 1)[1].split(
        "def _patched_tool_header_draw", 1
    )[0]
    assert "from ...core import viewport_guides" in HEADER
    assert 'cluster.operator(' in header
    assert '"mixar.zen_toggle_guides"' in header
    assert 'icon="GRID"' in header
    assert "depress=viewport_guides.guides_shown(view)" in header
    # Zen-only: Texturing keeps the shared shading strip without this chip.
    assert "if _is_basic_workspace(context):" in header
    assert header.index("mixar.zen_toggle_guides") < header.index(
        'popover(panel="VIEW3D_PT_shading"'
    )
    # Still outside the glass enum group, same cluster wiring as the popover.
    assert 'row.prop(shading, "type", text="", expand=True)' in header
    assert header.index('row.prop(shading, "type"') < header.index("mixar.zen_toggle_guides")


def test_guide_flag_list_covers_floor_axes_ortho_and_relationship():
    assert '"show_floor"' in CORE
    assert '"show_axis_x"' in CORE
    assert '"show_axis_y"' in CORE
    assert '"show_ortho_grid"' in CORE
    assert '"show_relationship_lines"' in CORE
