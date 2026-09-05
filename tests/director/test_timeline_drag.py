# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""First and last Director keyframes must stay draggable on the timeline."""

from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import timeline  # noqa: E402


def _read_view3d(name: str) -> str:
    return (VIEW3D / name).read_text(encoding="utf-8")


def _shot(frames):
    camera = SimpleNamespace(type="CAMERA", data=SimpleNamespace())
    beats = [SimpleNamespace(frame=frame) for frame in frames]
    return SimpleNamespace(
        state="DRAFT",
        beats=beats,
        camera=camera,
        manifest_json="",
    )


def _scene(*, frame_start=1, frame_end=48):
    return SimpleNamespace(
        frame_start=frame_start,
        frame_end=frame_end,
        frame_set=lambda _frame: None,
    )


def test_retiming_end_keyframes_does_not_refit_the_timeline_view():
    """Dragging the last (or first) keyframe used to re-fit the view.

    ``sync_view`` treated a change in the first/last beat frame as new
    content and called ``reset_view``, which glued that handle to the same
    pixel. Middle keys did not change the span, so only they looked
    draggable. Auto-fit now keys on shot identity or beat *count*.
    """
    draw = _read_view3d("view3d_director_timeline_draw.cc")
    interaction = _read_view3d("view3d_director_timeline_interaction.cc")

    assert "const bool count_changed = runtime->content_count != count;" in draw
    assert "(count_changed && !runtime->view_user_modified)" in draw
    assert "content_changed && !runtime->view_user_modified" not in draw
    # Beat drag pins the view the same way strip drag does.
    begin = interaction.split("bool begin_beat_drag", 1)[1].split(
        "bool begin_scrub", 1
    )[0]
    assert "runtime->view_user_modified = true;" in begin


def test_last_keyframe_stays_hittable_at_the_view_edge():
    """A handle whose centre sits on xmax must still receive a hit rect."""
    draw = _read_view3d("view3d_director_timeline_draw.cc")
    interaction = _read_view3d("view3d_director_timeline_interaction.cc")

    assert "hit_xmax < runtime->viewport_bounds.xmin" in draw
    assert "hit_xmin > runtime->viewport_bounds.xmax" in draw
    assert "x < runtime->viewport_bounds.xmin || x > runtime->viewport_bounds.xmax" not in draw
    # Last-drawn handle is on top when neighbours overlap.
    assert "int(runtime.beat_hits.size()) - 1" in interaction


def test_last_keyframe_can_slide_later_than_the_current_span(monkeypatch):
    monkeypatch.setattr(timeline, "_director_keyframes", lambda *a, **k: ([], []))
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)

    shot = _shot((1, 24, 48))
    scene = _scene(frame_end=48)
    delta = timeline.move_single_beat(scene, shot, 2, 12, rebuild_manifest=False)

    assert delta == 12
    assert shot.beats[2].frame == 60
    assert shot.beats[0].frame == 1
    assert shot.beats[1].frame == 24
    assert scene.frame_end == 60


def test_first_keyframe_can_slide_earlier_inside_the_scene_range(monkeypatch):
    monkeypatch.setattr(timeline, "_director_keyframes", lambda *a, **k: ([], []))
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)

    shot = _shot((10, 24, 48))
    scene = _scene(frame_start=1, frame_end=48)
    delta = timeline.move_single_beat(scene, shot, 0, -6, rebuild_manifest=False)

    assert delta == -6
    assert shot.beats[0].frame == 4
    assert shot.beats[1].frame == 24


def test_end_keyframes_still_cannot_cross_a_neighbour(monkeypatch):
    monkeypatch.setattr(timeline, "_director_keyframes", lambda *a, **k: ([], []))
    monkeypatch.setattr(timeline, "refresh_manifest", lambda *a, **k: None)

    last = _shot((1, 24, 48))
    last_scene = _scene(frame_end=48)
    assert timeline.move_single_beat(
        last_scene, last, 2, -40, rebuild_manifest=False
    ) == -23
    assert last.beats[2].frame == 25

    first = _shot((1, 24, 48))
    first_scene = _scene(frame_end=48)
    assert timeline.move_single_beat(
        first_scene, first, 0, 80, rebuild_manifest=False
    ) == 22
    assert first.beats[0].frame == 23
