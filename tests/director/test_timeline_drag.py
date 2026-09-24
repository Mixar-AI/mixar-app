# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""First and last keys must stay draggable on the timeline."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"


def _read_view3d(name: str) -> str:
    return (VIEW3D / name).read_text(encoding="utf-8")


def test_retiming_end_keyframes_does_not_refit_the_timeline_view():
    """Dragging the last (or first) keyframe used to re-fit the view.

    ``sync_view`` treated a change in the first/last beat frame as new
    content and called ``reset_view``, which glued that handle to the same
    pixel. Middle keys did not change the span, so only they looked
    draggable. Auto-fit keys on shot identity or beat *count*.
    """
    draw = _read_view3d("view3d_director_timeline_draw.cc")
    interaction = _read_view3d("view3d_director_timeline_interaction.cc")

    assert "const bool count_changed = runtime->content_count != count;" in draw
    assert "(count_changed && !runtime->view_user_modified)" in draw
    assert "content_changed && !runtime->view_user_modified" not in draw
    # The key drag pins the view the same way the strip drag does.
    begin = interaction.split("bool begin_key_drag", 1)[1].split("bool delete_keys", 1)[0]
    assert "runtime->view_user_modified = true;" in begin


def test_a_key_on_the_view_edge_is_still_a_hit():
    """A key whose centre sits on the last visible frame keeps its rect."""
    keys = _read_view3d("view3d_director_timeline_keys.cc")
    assert "if (!IN_RANGE_INCL(key.cfra, view_start, view_end)) {" in keys


def test_the_drag_is_clamped_by_the_scene_start_only():
    """Keys may overtake one another (the drop merges); only the scene's
    start, and Blender's frame limit, bound the offset."""
    source = (
        ROOT / "src/scripts/mixar/modules/director/core/key_drag.py"
    ).read_text(encoding="utf-8")
    clamp = source.split("def clamp(self", 1)[1].split("def apply(", 1)[0]
    assert "floor = min(float(self.scene.frame_start), first)" in clamp
    assert "upper = int(MAX_FRAME - last)" in clamp
