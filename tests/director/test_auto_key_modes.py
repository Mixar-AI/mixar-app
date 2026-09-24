# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Key watches every way a director actually moves a camera.

It used to run in Precise mode ALONE — the one mode the Cinema surface never
puts a director in. The surface's own ways of moving a camera are the WASD
nudge and the aerial-map placement, so Auto Key was on and did nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mixar.modules.director.core import auto_key


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    shot = SimpleNamespace(state='DRAFT', camera=SimpleNamespace(name="Camera"))
    monkeypatch.setattr(auto_key, "active_shot", lambda _scene: shot)
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: False)
    monkeypatch.setattr(auto_key, "_playing", lambda: False)
    return shot


def _scene(mode='NAVIGATE', *, auto=True, directing=True):
    return SimpleNamespace(
        mixar_director=SimpleNamespace(
            is_directing=directing, auto_key=auto, navigation_mode=mode
        )
    )


@pytest.mark.parametrize("mode", ['NAVIGATE', 'PRECISE', 'AERIAL'])
def test_every_mode_that_moves_the_shot_camera_is_watched(mode):
    state, shot = auto_key._watchable_shot(_scene(mode))
    assert state is not None and shot is not None


def test_explore_is_not_watched():
    """It parks the shot camera and flies a free view: no camera motion to
    key, and the pose that exists is stale."""
    assert auto_key._watchable_shot(_scene('EXPLORE')) == (None, None)


def test_a_running_walk_is_left_to_its_supervisor(monkeypatch):
    """`MIXAR_OT_director_navigate` captures ONCE on exit because it knows
    exactly when the move ended; a debounce underneath would litter the walk
    with keys every time the director paused to look.

    Deferring is a CAPTURE gate, not a watch gate — `_watchable_shot` still
    says yes, and `tests/director/test_auto_key_blender_parity.py` covers
    why the difference matters."""
    monkeypatch.setattr(auto_key, "move_in_progress", lambda: True)
    assert auto_key._deferring() is True
    assert auto_key._watchable_shot(_scene('NAVIGATE')) != (None, None)


def test_the_cinema_walk_is_the_walk_it_defers_to():
    """Naming only `VIEW3D_OT_walk` stopped being enough the moment Cinema
    Mode grew its own — and `MIXAR_OT_director_walk` is the one a director
    actually uses, so the debounce ran underneath every walk there is."""
    assert "MIXAR_OT_director_walk" in auto_key._DEFER_MODALS
    assert "VIEW3D_OT_walk" in auto_key._DEFER_MODALS


def test_an_unfinished_transform_is_waited_out():
    """Blender auto-keys when the transform CONFIRMS. A debounce that fires
    mid-drag — the director holds still while lining a shot up — keys a pose
    nobody chose and then keys the real one over it."""
    for name in ("TRANSFORM_OT_translate", "TRANSFORM_OT_rotate", "TRANSFORM_OT_resize"):
        assert name in auto_key._DEFER_MODALS


def test_playback_is_not_a_camera_move(monkeypatch):
    """Blender auto-keys from a transform and playback runs none; the poses
    streaming past ARE the animation."""
    monkeypatch.setattr(auto_key, "_playing", lambda: True)
    assert auto_key._deferring() is True


def test_auto_key_off_is_still_off():
    assert auto_key._watchable_shot(_scene(auto=False)) == (None, None)


def test_not_directing_is_still_not_watched():
    assert auto_key._watchable_shot(_scene(directing=False)) == (None, None)


def test_a_locked_take_is_never_keyed(monkeypatch):
    monkeypatch.setattr(
        auto_key, "active_shot", lambda _scene: SimpleNamespace(state='LOCKED', camera=object())
    )
    assert auto_key._watchable_shot(_scene()) == (None, None)


def test_modal_detection_never_raises_without_a_window(monkeypatch):
    """Handlers also run during file load, where there is no window."""
    monkeypatch.setattr(auto_key.bpy, "context", SimpleNamespace(window=None))
    assert auto_key.move_in_progress() is False
    monkeypatch.setattr(
        auto_key.bpy,
        "context",
        SimpleNamespace(window=SimpleNamespace(modal_operators=None)),
    )
    assert auto_key.move_in_progress() is False


def test_playback_detection_never_raises_without_a_screen(monkeypatch):
    monkeypatch.setattr(auto_key.bpy, "context", SimpleNamespace(screen=None))
    assert auto_key._playing() is False
