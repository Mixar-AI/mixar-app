# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The eyedropper shows what it is about to pick.

It used to be a cursor and nothing else: the director clicked and found out
afterwards what had been picked, and a miss was indistinguishable from a hit
on the wrong object.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.ui import track_pick_overlay

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = (
    ROOT / "src/scripts/mixar/modules/director/ui/track_pick_overlay.py"
).read_text(encoding="utf-8")
OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/track_ops.py"
).read_text(encoding="utf-8")


def teardown_function(_func):
    track_pick_overlay._hover.update({"object": None, "mouse": (0, 0), "region": None})


def test_set_hover_reports_only_real_changes():
    """A redraw per mouse move over the same object is a redraw per frame."""
    first, second = object(), object()
    assert track_pick_overlay.set_hover(first, (1, 2)) is True
    assert track_pick_overlay.set_hover(first, (3, 4)) is False
    assert track_pick_overlay.set_hover(second, (3, 4)) is True
    assert track_pick_overlay.set_hover(None, (3, 4)) is True


def test_set_hover_keeps_the_pointer_position_even_when_unchanged():
    """The label follows the cursor, not just the object."""
    obj = object()
    track_pick_overlay.set_hover(obj, (1, 2))
    track_pick_overlay.set_hover(obj, (30, 40))
    assert track_pick_overlay._hover["mouse"] == (30, 40)


def test_the_outline_and_the_label_draw_in_their_own_spaces():
    """World geometry is POST_VIEW; screen text is POST_PIXEL."""
    assert "_draw_outline, (), 'WINDOW', 'POST_VIEW'" in OVERLAY
    assert "_draw_label, (), 'WINDOW', 'POST_PIXEL'" in OVERLAY


def test_both_callbacks_are_scoped_to_the_region_that_started_the_pick():
    """A second viewport must not paint a hover the user is not making."""
    # Once in each callback, plus the definition.
    assert OVERLAY.count("_region_matches()") == 3
    body = OVERLAY[OVERLAY.index("def _region_matches(") :]
    body = body[: body.index("\ndef ")]
    assert "region.as_pointer() == _hover[\"region\"]" in body


def test_enable_drops_any_previous_handlers_first():
    """A modal that never reached its exit cannot strand a handler with
    nothing able to reach it."""
    body = OVERLAY[OVERLAY.index("def enable(") :]
    body = body[: body.index("\ndef ")]
    assert body.index("disable()") < body.index("draw_handler_add")


def test_disable_is_safe_to_call_repeatedly():
    body = OVERLAY[OVERLAY.index("def disable(") :]
    assert "except (ValueError, ReferenceError, RuntimeError):" in body
    track_pick_overlay.disable()
    track_pick_overlay.disable()


def test_gpu_modules_are_imported_inside_the_callbacks():
    """The module is auto-discovered at startup and must not need a GPU
    context merely to be imported."""
    tree = ast.parse(OVERLAY)
    top_level = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert top_level & {"bpy"}
    assert not top_level & {"gpu", "blf", "mathutils", "batch_for_shader"}


def _modal() -> str:
    tree = ast.parse(OPS)
    return ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "modal"
        )
    )


def test_the_modal_tracks_the_pointer():
    modal = _modal()
    assert "if event.type == 'MOUSEMOVE'" in modal
    assert "self._hover(context, event)" in modal


def test_a_failed_hover_never_ends_the_pick():
    """A ray cast that raises mid-hover must not cancel the eyedropper."""
    tree = ast.parse(OPS)
    hover = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_hover"
        )
    )
    assert "except Exception" in hover
    assert "target = None" in hover
    # The shot camera is not a target it can track, so it is not offered.
    assert "target == shot.camera" in hover


def test_every_exit_takes_the_overlay_down():
    tree = ast.parse(OPS)
    for name in ("modal", "cancel"):
        body = ast.unparse(
            next(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
        )
        assert "self._end()" in body, name
    end = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_end"
        )
    )
    assert "disable_hover()" in end


def test_the_overlay_is_enabled_for_the_region_the_pick_started_in():
    tree = ast.parse(OPS)
    invoke = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "invoke"
        )
    )
    # The hover is scoped to a real 3D viewport region, never to whatever
    # `context` happens to name: the focus eyedropper starts from a popup,
    # whose own temporary region would paint nothing.
    assert "enable_hover(region)" in invoke
    viewport = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_viewport"
        )
    )
    assert "region.type == 'WINDOW'" in viewport
    assert "area.type == 'VIEW_3D'" in viewport
    assert "find_view3d_context(context)" in viewport
