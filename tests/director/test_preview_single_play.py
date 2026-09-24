# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview plays the shot ONCE and parks on the last keyframe.

Blender's player always wraps at the end of the (preview) range. For a director
reviewing a shot that reads as a bug — the preview never ends. Director arms a
one-shot stop around its own playback only; ordinary Blender playback keeps
looping everywhere else.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import playback

_OPS = (
    Path(__file__).resolve().parents[2]
    / "src/scripts/mixar/modules/director/ui/operators/capture_ops.py"
)


def teardown_function(_func):
    playback.disarm()


def test_stops_on_the_end_frame():
    assert playback.should_stop(50, 1, 50) is True
    assert playback.should_stop(49, 1, 50) is False


def test_stops_past_the_end_frame():
    """A frame step over one can overshoot the end without landing on it."""
    assert playback.should_stop(53, 1, 50) is True


def test_stops_on_the_wrap():
    """The case a bare `frame >= end` misses.

    Blender advances the playhead and notifies afterwards, so under load or a
    frame step the handler can never see the end frame at all — only the
    wrapped one back at the start. Only once the playhead HAS advanced, which
    is what the fourth argument carries.
    """
    assert playback.should_stop(1, 1, 50, True) is True
    assert playback.should_stop(0, 1, 50, True) is True
    assert playback.should_stop(2, 1, 50, True) is False


def test_the_start_frame_is_not_a_wrap_before_the_playhead_moves():
    """Preview looked like it only jumped to the last keyframe.

    The player's first notification after `animation_play` is frequently the
    start frame itself — a zero-sized step in a sync/frame-drop mode, or the
    re-notify after the frame was just set. Read as a completed wrap, that
    stopped the player and parked the playhead on the END frame before one
    frame had been shown, which is exactly what a director saw.
    """
    assert playback.should_stop(1, 1, 50, False) is False
    assert playback.should_stop(0, 1, 50, False) is False
    # The end rule is unconditional: an armed playback already sitting at or
    # past its end still stops.
    assert playback.should_stop(50, 1, 50, False) is True


def test_the_handler_waits_for_the_playhead_to_leave_the_start():
    """End to end over the real handler, with a scene that stands still."""
    stopped = []
    scene = SimpleNamespace(
        name="Scene",
        as_pointer=lambda: 99,
        frame_current=1,
        frame_set=lambda frame: stopped.append(frame),
    )
    playback.arm_single_play(scene, 1, 50)

    # The player has not moved yet: several notifications at the start frame.
    for _ in range(3):
        playback._on_frame_change(scene)
    assert stopped == [], "Preview stopped before it ever played"
    assert playback.is_armed() is True

    # It plays.
    for frame in (2, 20, 49):
        scene.frame_current = frame
        playback._on_frame_change(scene)
    assert stopped == []
    assert playback.is_armed() is True

    # Now a frame back at the start really is the wrap.
    scene.frame_current = 1
    playback._on_frame_change(scene)
    assert stopped == [50], "the wrap must park on the last keyframe"
    assert playback.is_armed() is False


def test_the_handler_still_stops_on_the_end_frame():
    stopped = []
    scene = SimpleNamespace(
        name="Scene",
        as_pointer=lambda: 99,
        frame_current=1,
        frame_set=lambda frame: stopped.append(frame),
    )
    playback.arm_single_play(scene, 1, 50)
    for frame in (2, 30, 50):
        scene.frame_current = frame
        playback._on_frame_change(scene)
    assert stopped == [50]
    assert playback.is_armed() is False


def test_arming_clears_a_previous_run_advance():
    scene = SimpleNamespace(
        name="Scene", as_pointer=lambda: 99, frame_current=9, frame_set=lambda _f: None
    )
    playback.arm_single_play(scene, 1, 50)
    playback._on_frame_change(scene)  # advances
    playback.arm_single_play(scene, 1, 50)  # a second Preview
    assert playback._armed["advanced"] is False


def test_a_single_frame_range_never_reads_as_a_wrap():
    assert playback.should_stop(7, 7, 7, False) is True
    assert playback.should_stop(6, 7, 7, False) is False


def test_arm_and_disarm():
    scene = SimpleNamespace(as_pointer=lambda: 4242)
    assert playback.is_armed() is False
    playback.arm_single_play(scene, 1, 50)
    assert playback.is_armed() is True
    playback.disarm()
    assert playback.is_armed() is False


def test_preview_arms_the_stop_and_pause_does_not():
    """Source-level: `bpy.types.Operator` is a mock, so pin the shape.

    Play must arm; the pause branch (already playing) must disarm rather than
    arm, or a pause would leave a stop waiting for the next unrelated playback.
    """
    source = _OPS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    preview = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "MIXAR_OT_director_preview"
    )
    execute = next(
        node
        for node in preview.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute"
    )
    calls = [
        node.func.id
        for node in ast.walk(execute)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "arm_single_play" in calls
    assert "disarm" in calls

    # The arm must happen on the not-playing branch, guarded by the playing
    # check — never unconditionally.
    playing_check = next(
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.If)
        and "is_animation_playing" in ast.unparse(node.test)
    )
    armed_in_pause_branch = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "arm_single_play"
        for statement in playing_check.body
        for node in ast.walk(statement)
    )
    assert not armed_in_pause_branch


def test_the_watcher_bridge_is_discoverable():
    bridge = (
        Path(__file__).resolve().parents[2]
        / "src/scripts/mixar/modules/director/ui/playback_watch.py"
    )
    source = bridge.read_text(encoding="utf-8")
    assert "def register" in source and "def unregister" in source


def test_the_frame_handler_never_disarms_on_a_context_read():
    """The bug this replaces.

    The handler used to read `bpy.context.screen.is_animation_playing` and
    disarm when it was False. A frame-change handler runs with whatever
    context Blender happens to be in — on a screen that is not the playing
    one that read False on the very FIRST frame change, disarmed immediately,
    and the preview looped forever.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "src/scripts/mixar/modules/director/core/playback.py"
    ).read_text(encoding="utf-8")
    handler = source[source.index("def _on_frame_change(") :]
    handler = handler[: handler.index("\n@persistent")]
    assert "is_animation_playing" not in handler
    assert "bpy.context" not in handler


def test_playback_ending_by_any_route_disarms():
    """`animation_playback_post` is the handler that exists for this."""
    source = (
        Path(__file__).resolve().parents[2]
        / "src/scripts/mixar/modules/director/core/playback.py"
    ).read_text(encoding="utf-8")
    assert '("animation_playback_post", "_on_playback_end")' in source
    body = source[source.index("def _on_playback_end(") :]
    assert "disarm()" in body


def test_parking_the_playhead_does_not_re_enter_the_handler():
    """`frame_set` inside `frame_change_post` fires it again."""
    scene = SimpleNamespace(as_pointer=lambda: 7, name="Scene")
    playback.arm_single_play(scene, 1, 50)
    playback._stopping["busy"] = True
    try:
        # Armed, on the armed scene, past the end — and still ignored.
        scene.frame_current = 99
        playback._on_frame_change(scene)
        assert playback.is_armed() is True
    finally:
        playback._stopping["busy"] = False


def test_the_armed_scene_is_matched_by_name_as_well_as_pointer():
    """The handler's scene argument is not guaranteed to be the same
    PyObject as the one the operator armed."""
    playback.arm_single_play(SimpleNamespace(as_pointer=lambda: 11, name="Scene"), 1, 50)
    assert playback._is_armed_scene(SimpleNamespace(as_pointer=lambda: 11, name="Other"))
    assert playback._is_armed_scene(SimpleNamespace(as_pointer=lambda: 99, name="Scene"))
    assert not playback._is_armed_scene(SimpleNamespace(as_pointer=lambda: 99, name="Other"))
    assert not playback._is_armed_scene(None)


# ---- the dock's playhead has to move while the player runs ----------------


def _fake_screens(monkeypatch, *region_types):
    """A window manager whose one VIEW_3D area carries *region_types*."""
    tagged = []

    def _region(kind):
        return SimpleNamespace(type=kind, tag_redraw=lambda k=kind: tagged.append(k))

    area = SimpleNamespace(type='VIEW_3D', regions=[_region(k) for k in region_types])
    other = SimpleNamespace(type='OUTLINER', regions=[_region('CHANNELS')])
    window = SimpleNamespace(screen=SimpleNamespace(areas=[area, other]))
    monkeypatch.setattr(
        playback.bpy,
        "data",
        SimpleNamespace(window_managers=[SimpleNamespace(windows=[window])]),
        raising=False,
    )
    return tagged


def _directing_scene(**extra):
    values = {
        "name": "Scene",
        "as_pointer": lambda: 7,
        "frame_current": 5,
        "frame_set": lambda _f: None,
        "mixar_director": SimpleNamespace(is_directing=True),
    }
    values.update(extra)
    return SimpleNamespace(**values)


def test_the_dock_redraws_on_every_frame_change(monkeypatch):
    """Blender suppresses notifiers during playback and tags regions itself,
    and it knows nothing about a CHANNELS region inside a View3D — so the
    dock's own listener never fires and its playhead stands still while the
    viewport plays."""
    tagged = _fake_screens(monkeypatch, 'WINDOW', 'CHANNELS', 'UI')

    playback._on_frame_change(_directing_scene())

    assert tagged == ['CHANNELS'], "only the dock, and only in a VIEW_3D"


def test_the_dock_redraws_for_playback_director_did_not_start(monkeypatch):
    """Space over the viewport must move the dock's playhead too."""
    tagged = _fake_screens(monkeypatch, 'CHANNELS')
    assert playback.is_armed() is False

    playback._on_frame_change(_directing_scene())

    assert tagged == ['CHANNELS']


def test_no_director_session_touches_nothing(monkeypatch):
    tagged = _fake_screens(monkeypatch, 'CHANNELS')

    playback._on_frame_change(
        _directing_scene(mixar_director=SimpleNamespace(is_directing=False))
    )
    playback._on_frame_change(_directing_scene(mixar_director=None))

    assert tagged == []


def test_a_redraw_tag_never_breaks_playback(monkeypatch):
    """A dead window list must not take the stop handler down with it."""
    class _Hostile:
        @property
        def window_managers(self):
            raise RuntimeError("no window managers")

    monkeypatch.setattr(playback.bpy, "data", _Hostile(), raising=False)
    stopped = []
    scene = _directing_scene(frame_current=50, frame_set=lambda f: stopped.append(f))
    playback.arm_single_play(scene, 1, 50)

    playback._on_frame_change(scene)

    assert stopped == [50], "the stop still has to run"


# ---- the range that plays is the SCENE's ----------------------------------


def test_any_playback_in_a_session_is_armed_to_stop(monkeypatch):
    """Space over the viewport is the same request as the Preview button, and
    a timeline that runs forever is the same wrong answer whichever started
    it."""
    scene = SimpleNamespace(
        frame_start=1,
        frame_end=250,
        name="Scene",
        as_pointer=lambda: 7,
        mixar_director=SimpleNamespace(is_directing=True),
    )
    playback._on_playback_start(scene)
    assert playback.is_armed() is True
    assert playback._armed["start_frame"] == 1
    assert playback._armed["end_frame"] == 250


def test_playback_outside_a_session_keeps_looping(monkeypatch):
    """Ordinary Blender playback is untouched — the arming only ever happens
    while a session is directing."""
    scene = SimpleNamespace(
        frame_start=1,
        frame_end=250,
        name="Scene",
        as_pointer=lambda: 7,
        mixar_director=SimpleNamespace(is_directing=False),
    )
    playback._on_playback_start(scene)
    assert playback.is_armed() is False


def test_the_preview_buttons_own_arming_wins():
    """It arms before it starts the player, so the handler must not overwrite
    it — Preview rewinds to the start, Space plays from where it is."""
    scene = SimpleNamespace(
        frame_start=1,
        frame_end=250,
        name="Scene",
        as_pointer=lambda: 7,
        mixar_director=SimpleNamespace(is_directing=True),
    )
    playback.arm_single_play(scene, 10, 90)
    playback._on_playback_start(scene)
    assert (playback._armed["start_frame"], playback._armed["end_frame"]) == (10, 90)


def test_an_empty_range_is_not_armed():
    scene = SimpleNamespace(
        frame_start=100,
        frame_end=100,
        name="Scene",
        as_pointer=lambda: 7,
        mixar_director=SimpleNamespace(is_directing=True),
    )
    playback._on_playback_start(scene)
    assert playback.is_armed() is False


def test_preview_plays_the_scene_range_not_the_keyframes():
    """Two keyframes used to mean a two-keyframe loop, whatever End said."""
    source = _OPS.read_text(encoding="utf-8")
    body = source[source.index("class MIXAR_OT_director_preview") :]
    body = body[: body.index("\n\nclass ")]
    assert "release_preview_range(scene)" in body
    assert "start_frame = int(scene.frame_start)" in body
    assert "end_frame = int(scene.frame_end)" in body
    assert "arm_single_play(scene, start_frame, end_frame)" in body
    # Never the beats' own span again.
    assert "frame_preview_start" not in body
    assert "arm_single_play(scene, frames[0], frames[-1])" not in body
