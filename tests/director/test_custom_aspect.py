# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A ratio the presets do not cover."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/aspect_ops.py"
).read_text(encoding="utf-8")
POPUP = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_popup.cc"
).read_text(encoding="utf-8")

_SOURCE = OPS
_TREE = ast.parse(OPS)
_OPERATOR = next(
    node
    for node in _TREE.body
    if isinstance(node, ast.ClassDef)
    and node.name == "MIXAR_OT_director_set_custom_aspect"
)


def _method(name: str) -> str:
    node = next(
        item
        for item in _OPERATOR.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.unparse(node)


def test_the_ratio_is_edited_in_the_popup_itself():
    """It used to be a "Custom..." row running `invoke_props_dialog` — that
    is Blender's STOCK dialog, grey chrome and OK/Cancel, nothing like the
    glass popup it opened from. A ratio is two numbers, and the popup stays
    open, so the two numbers live in it."""
    assert '"MIXAR_OT_director_set_custom_aspect"' in POPUP
    assert '"Custom..."' not in POPUP
    assert '"custom_aspect_x"' in POPUP
    assert '"custom_aspect_y"' in POPUP
    # One row applies what the two fields hold.
    assert '"Frame at this ratio"' in POPUP


def test_the_fields_are_on_the_director_state():
    """Operator properties could not be edited across a block, and the state
    is what every other popup field binds to."""
    properties = (
        ROOT / "src/scripts/mixar/modules/director/ui/properties/director_properties.py"
    ).read_text(encoding="utf-8")
    for field in ("custom_aspect_x", "custom_aspect_y"):
        assert f"{field}: IntProperty(" in properties
    # Bound to the state, not to operator properties, which cannot be
    # edited across a block.
    flat = " ".join(POPUP.split())
    assert '&data.state_ptr, "custom_aspect_x"' in flat
    assert '&data.state_ptr, "custom_aspect_y"' in flat


def test_the_custom_row_lights_when_no_preset_matches():
    """Otherwise a custom ratio leaves the whole list looking unselected."""
    assert "matched |= active;" in POPUP
    assert "director_popup_state(custom, !matched, data.editable);" in POPUP


def test_no_stock_dialog_is_opened():
    assert "invoke_props_dialog" not in _SOURCE
    assert "def invoke" not in _SOURCE
    assert "def draw" not in _SOURCE


def test_the_surfaces_fields_are_what_it_applies():
    """And a script or the agent can still pass the ratio directly, which
    wins — the surface simply never sets the properties."""
    ratio = _method("_ratio")
    assert "is_property_set" in ratio and "ratio_width" in ratio
    assert "state.custom_aspect_x" in ratio
    assert "state.custom_aspect_y" in ratio
    # No state at all (a bare script call) still has an honest answer.
    assert "scene_ratio(context.scene)" in ratio
    assert "normalise_ratio(*self._ratio(context))" in _method("execute")


def test_it_stores_a_ratio_on_the_camera_and_applies_it():
    execute = _method("execute")
    assert "normalise_ratio(" in execute
    assert "remember_camera_ratio(shot.camera" in execute
    assert "apply_ratio(context.scene" in execute
    # A pixel size would make aspect and the resolution tier fight again.
    assert "resolution_x" not in execute
    assert "resolution_y" not in execute


def test_a_locked_take_cannot_reshape_the_frame():
    helper = ast.unparse(
        next(
            node
            for node in _TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "_editable_shot"
        )
    )
    assert "shot.state != 'DRAFT'" in helper
    assert "_editable_shot(context) is not None" in _method("poll")


def test_the_ratio_bounds_are_generous_not_tight():
    """2048:858 is a real DCI ratio; nobody should have to reduce it by hand."""
    for field in ("ratio_width", "ratio_height"):
        assign = next(
            item
            for item in _OPERATOR.body
            if isinstance(item, ast.AnnAssign) and item.target.id == field
        )
        call = ast.unparse(assign.annotation)
        assert "min=1" in call
        assert "max=100000" in call
