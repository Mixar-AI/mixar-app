# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview plays into the VIEWPORT, not into the region it was clicked in.

Blender redraws the region playback was started from, plus whatever the
Playback popover's `redraws_flag` adds — which is nothing by default. The
Preview button lives in the timeline dock, a region of its own, so starting
the player from it ran the shot into a viewport that never redrew: the frames
advanced and the picture did not move. Pressing Space works because the
pointer is over the viewport, and that IS the region it starts from.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
CAPTURE_OPS = (DIRECTOR / "ui/operators/capture_ops.py").read_text(encoding="utf-8")
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
TRANSPORT = (VIEW3D / "view3d_director_cinema_dock_transport.cc").read_text(encoding="utf-8")
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")


def _method(name: str) -> str:
    tree = ast.parse(CAPTURE_OPS)
    operator = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MIXAR_OT_director_preview"
    )
    return ast.unparse(
        next(
            node
            for node in operator.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
    )


def test_the_player_is_started_from_the_viewport():
    toggle = _method("_toggle_playback")
    assert "find_view3d_context(context)" in toggle
    assert "context.temp_override(" in toggle
    assert "window=window" in toggle and "area=area" in toggle and "region=region" in toggle
    assert "bpy.ops.screen.animation_play()" in toggle


def test_a_session_with_no_viewport_still_plays():
    """Refusing to play at all would be worse than playing unwatched."""
    toggle = _method("_toggle_playback")
    assert "if target is None" in toggle


def test_both_the_start_and_the_stop_go_through_it():
    """The Preview slot doubles as pause; a stop started from the dock has
    the same redraw problem as a start."""
    execute = _method("execute")
    assert execute.count("self._toggle_playback(context)") == 2
    assert "bpy.ops.screen.animation_play()" not in execute


def test_a_refusal_is_reported_rather_than_returned():
    """It used to be handed back verbatim, so a Preview that never started
    read as success to everything upstream."""
    execute = _method("execute")
    assert "if 'FINISHED' not in result" in execute
    assert "disarm()" in execute.split("if 'FINISHED' not in result", 1)[1]
    assert "'CANCELLED'" in execute.split("if 'FINISHED' not in result", 1)[1]


def test_the_stop_is_never_armed():
    execute = _method("execute")
    pause = execute.split("is_animation_playing", 1)[1].split("scene.frame_set", 1)[0]
    assert "disarm()" in pause
    assert "arm_single_play" not in pause


def test_a_missing_screen_does_not_raise():
    """`context.screen` is None in plenty of contexts an operator can run in."""
    execute = _method("execute")
    assert "getattr(context, 'screen', None)" in execute
    assert "getattr(screen, 'is_animation_playing', False)" in execute


def test_the_dock_keeps_redrawing_itself_while_playing():
    """Anchoring the player on the viewport must not stop the playhead
    moving in the dock; the dock runs its own notifier timer for that."""
    assert "playback_redraw_timer_update(C, playing)" in TIMELINE
    assert "WM_event_timer_add_notifier(" in TIMELINE
    assert "NC_SPACE | ND_SPACE_VIEW3D" in TIMELINE


def test_the_transport_middle_slot_is_preview():
    assert '{"MIXAR_OT_director_preview", true, false, "Preview this shot"}' in TRANSPORT
