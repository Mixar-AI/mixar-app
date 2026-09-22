# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`lock_camera` is ON for the whole Cinema Mode session.

"Lock Camera to View" makes a viewport orbit, pan or dolly move the CAMERA
rather than the view. In Cinema Mode the camera is what the director is
moving, so that is the mode, not a side effect — every path into a camera
holds it on, and walk only borrows something the mode already has.

It was briefly off, because a wheel aimed at the My Cameras card was dollying
the shot. That is fixed where it belongs, below: the scroll operator's poll
absorbs the wheel over the columns, so the lock does not have to pay for it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import viewport

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEWPORT = (DIRECTOR / "core/viewport.py").read_text(encoding="utf-8")
CAMERA_OPS = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
CAMERAS = (VIEW3D / "view3d_director_cinema_cameras.cc").read_text(encoding="utf-8")
#: The wheel/trackpad gesture, split out of the card when the painter
#: reached the module size limit.
SCROLL = (VIEW3D / "view3d_director_cinema_camera_scroll.cc").read_text(encoding="utf-8")
LAYOUT = (VIEW3D / "view3d_director_cinema_layout.cc").read_text(encoding="utf-8")


def _enter_camera_view(lock_before):
    space = SimpleNamespace(
        region_3d=SimpleNamespace(view_perspective='PERSP'),
        lock_camera=lock_before,
        camera=None,
    )
    area = SimpleNamespace(tag_redraw=lambda: None)
    scene = SimpleNamespace(mixar_director=SimpleNamespace(navigation_mode='NAVIGATE'), camera=None)
    original = viewport.find_view3d_context
    viewport.find_view3d_context = lambda _context: (None, area, None, space)
    try:
        viewport.enter_camera_view(SimpleNamespace(scene=scene), "camera", remember=False)
    finally:
        viewport.find_view3d_context = original
    return space


def test_looking_through_a_camera_locks_it_to_the_view():
    """"Toggle: enable view navigation within the camera view" is the mode."""
    assert _enter_camera_view(False).lock_camera is True


def test_an_already_locked_view_stays_locked():
    """Every flow lands here — a capture, a shot switch, Back to Shot — and
    none of them may quietly hand navigation back to the view."""
    assert _enter_camera_view(True).lock_camera is True


def test_walk_still_holds_it_on_for_itself():
    """Belt and braces for a viewport not entered through `enter_camera_view`."""
    walk = VIEWPORT.split("def invoke_walk(", 1)[1].split("\ndef ", 1)[0]
    assert "space.lock_camera = True" in walk
    assert walk.index("enter_camera_view(") < walk.index("space.lock_camera = True")


def test_only_the_modes_that_leave_the_camera_turn_it_off():
    """Explore and Aerial are free views and Precise is gizmo work, so the
    lock is meaningless in all three. Everywhere else it stays on — and
    `enter_camera_view`, the path every other flow takes, never clears it."""
    bodies = {
        name: VIEWPORT.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
        for name in ("enter_camera_view", "enter_free_view", "enter_aerial_view",
                     "enter_precise_mode")
    }
    assert "lock_camera = False" not in bodies["enter_camera_view"]
    for name in ("enter_free_view", "enter_aerial_view", "enter_precise_mode"):
        assert "space.lock_camera = False" in bodies[name], name
    # Three, and only three.
    assert VIEWPORT.count("space.lock_camera = False") == 3


def test_the_supervisor_does_not_release_it_on_exit():
    """The walk did not ask for the lock — the mode did — so ending a walk
    must not take viewport navigation away from the rest of the session."""
    assert "_release_camera_lock" not in CAMERA_OPS
    assert "lock_camera = False" not in CAMERA_OPS


def test_the_supervisor_publishes_whether_a_walk_is_running():
    """The top strip's hints promise walk's keys only while walk has them."""
    tree = ast.parse(CAMERA_OPS)
    supervise = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_supervise"
        )
    )
    assert "set_walk_active(context, True)" in supervise
    finish = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_finish"
        )
    )
    assert "set_walk_active(context, False)" in finish
    # `cancel()` is an exit too (file load, an exception): it goes through
    # `_finish`, so the clear covers it.
    cancel = ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "cancel"
        )
    )
    assert "self._finish(" in cancel


# -------------------------------------------------------------------------
# The wheel over a painted card.


def test_the_wheel_is_absorbed_anywhere_on_a_card():
    poll = SCROLL.split("bool camera_list_scroll_poll(", 1)[1].split("\n}", 1)[0]
    assert "cinema_camera_list_contains(region, x, y)" in poll
    assert "cinema_columns_contain(C, region, x, y)" in poll


def test_only_the_rows_actually_scroll():
    """A wheel over the Template Style card must not move a list it is not on."""
    invoke = SCROLL.split("camera_list_scroll_invoke(", 1)[1].split("\n}", 1)[0]
    assert "cinema_camera_list_contains(region, event->mval[0], event->mval[1])" in invoke
    assert "cinema_camera_list_scroll(" in invoke
    assert "return OPERATOR_FINISHED;" in invoke


def test_the_keymap_reaches_invoke():
    assert "ot->invoke = camera_list_scroll_invoke;" in SCROLL


def test_the_stage_keeps_the_wheel():
    """Zoom is the viewport's between the columns; only the cards take it."""
    contains = LAYOUT.split("bool cinema_columns_contain(", 1)[1].split("\n}\n", 1)[0]
    assert "margin + CINEMA_PANEL_W" in contains
    assert "CINEMA_STAGE_INSET" not in contains


def test_the_compact_rail_owns_no_column_band():
    contains = LAYOUT.split("bool cinema_columns_contain(", 1)[1].split("\n}\n", 1)[0]
    assert "cinema_surface_fits(region)" in contains
    assert "return false;" in contains.split("cinema_surface_fits(region)", 1)[1]
