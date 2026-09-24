# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A camera deleted outside Director takes its shots with it.

Deleting from the outliner, the viewport or a script clears every RNA pointer
to the camera, leaving a take that directs nothing: the timeline keeps its
strip and the session keeps counting it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mixar.modules.director.core import camera_sync


def _state(shots):
    return SimpleNamespace(shots=list(shots))


def _shot(shot_id, camera):
    return SimpleNamespace(shot_id=shot_id, camera=camera)


@pytest.fixture(autouse=True)
def _clean():
    camera_sync._seen.clear()
    camera_sync._pending["prune"] = False
    yield
    camera_sync._seen.clear()
    camera_sync._pending["prune"] = False


def test_a_shot_that_never_held_a_camera_is_not_a_deletion():
    """A session being built has a camera-less shot for a moment, and a file
    saved before this watcher existed must not lose shots on load."""
    state = _state([_shot("a", None)])
    assert camera_sync.orphaned_shot_indices(state) == []


def test_a_shot_that_held_a_camera_and_lost_it_is_a_deletion():
    camera = SimpleNamespace(name="Camera")
    state = _state([_shot("a", camera)])
    camera_sync._observe(state)
    assert camera_sync.orphaned_shot_indices(state) == []

    # Blender clears every pointer to a removed ID.
    state.shots[0].camera = None
    assert camera_sync.orphaned_shot_indices(state) == [0]


def test_only_the_shots_of_the_deleted_camera_are_orphaned():
    kept = SimpleNamespace(name="Camera.001")
    gone = SimpleNamespace(name="Camera")
    state = _state([_shot("a", gone), _shot("b", kept), _shot("c", gone)])
    camera_sync._observe(state)
    state.shots[0].camera = None
    state.shots[2].camera = None
    assert camera_sync.orphaned_shot_indices(state) == [0, 2]


def test_the_memory_does_not_grow_for_the_life_of_the_session():
    camera = SimpleNamespace(name="Camera")
    state = _state([_shot("a", camera), _shot("b", camera)])
    camera_sync._observe(state)
    assert set(camera_sync._seen) == {"a", "b"}
    state.shots.pop(0)
    camera_sync._observe(state)
    assert set(camera_sync._seen) == {"b"}


def test_a_shot_without_an_id_is_ignored():
    """`shot_id` is the stable key across the collection reallocations that
    adding a shot causes; without one there is nothing to remember."""
    state = _state([_shot("", None)])
    camera_sync._observe(state)
    assert camera_sync.orphaned_shot_indices(state) == []
    assert camera_sync._seen == {}


def test_loading_a_file_forgets_the_previous_files_shots():
    camera = SimpleNamespace(name="Camera")
    camera_sync._observe(_state([_shot("a", camera)]))
    camera_sync._pending["prune"] = True
    camera_sync._on_load(None)
    assert camera_sync._seen == {}
    assert camera_sync._pending["prune"] is False
    # A shot arriving camera-less from the new file is not this session's
    # deletion.
    assert camera_sync.orphaned_shot_indices(_state([_shot("a", None)])) == []


def test_the_handler_only_flags_and_the_timer_mutates():
    """Mutating scene data inside `depsgraph_update_post` is unsafe; the same
    split `beat_sync` uses."""
    import ast
    import inspect

    handler = ast.parse(inspect.getsource(camera_sync._on_depsgraph_update))
    called = {
        node.func.id
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "remove_shot" not in called
    assert "_ensure_timer" in called

    timer = ast.parse(inspect.getsource(camera_sync._prune_timer))
    timer_calls = {
        node.func.id
        for node in ast.walk(timer)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "remove_shot" in timer_calls


def test_shots_are_removed_highest_index_first():
    source = __import__("inspect").getsource(camera_sync._prune_timer)
    assert "reverse=True" in source
