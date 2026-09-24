# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Key refines the playhead's keyframe instead of marching past it.

Blender's own auto-key rule is "key the current frame". Director's capture
appends by default, which is right for the repeat-capture quick flow: press
the button again, get the next keyframe one beat further on. Under Auto Key
that rule is wrong — the director nudges, looks, nudges again, all at one
frame — so every adjustment marched a NEW keyframe forward through the shot
instead of refining the one under the playhead.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import capture

ROOT = pathlib.Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/director"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_both_auto_key_paths_replace_the_playheads_keyframe():
    """The debounced watcher and the walk supervisor are the two of them."""
    debounce = _read("core/auto_key.py").split("def _debounce_timer", 1)[1]
    assert "capture_beat(" in debounce
    assert "replace_existing=True" in debounce

    walk = _read("ui/operators/camera_ops.py").split("_auto_capture", 1)[1]
    assert "capture_beat(" in walk
    assert "replace_existing=True" in walk


def test_manual_capture_still_appends():
    """The Capture button is the repeat-capture quick flow; it must not
    overwrite the keyframe the director is parked on."""
    for relative in (
        "ui/operators/capture_ops.py",
        "ui/operators/template_ops.py",
        "core/camera_moves.py",
    ):
        source = _read(relative)
        assert "capture_beat(context, shot, state.beat_seconds)" in source
        assert "replace_existing" not in source


def test_the_playheads_own_frame_is_reused_only_when_replacing():
    source = _read("core/capture.py").split("def capture_beat", 1)[1]
    fallback = source.split("target_frame = int(scene.frame_current)", 1)[1]
    fallback, lookup = fallback.split("existing_index = -1", 1)
    lookup = lookup.split("try:", 1)[0]
    # Only the replace path keeps the playhead's own frame from falling
    # through to the stride.
    assert "target_frame < scene.frame_start" in fallback
    assert "target_frame in taken and not replace_existing" in fallback
    # And the beat it will replace is looked up AFTER that fallback has had
    # its say, against the frame the keyframe actually lands on. Resolved
    # first, the index can point at a beat on another frame entirely — whose
    # still would be replaced with a render of a pose keyed somewhere else.
    assert "if replace_existing:" in lookup
    assert "int(beat.frame) == target_frame" in lookup
    assert fallback.index("next_beat_frame") < len(fallback)


def test_replacing_keeps_the_beats_identity_and_timing():
    """`beat_id`, `frame` and `time_base` are what the strip, the manifest
    and the Speed slider identify a beat by; re-keying must not churn them."""
    branch = _read("core/capture.py").split("if existing_index >= 0:", 1)[1]
    branch = branch.split("        else:", 1)[0]
    assert "beat_id" not in branch
    assert ".frame" not in branch
    assert "note_beat_timing" not in branch
    assert "beat.image = image" in branch


class _Image:
    def __init__(self, users=0):
        self.users = users


class _Data:
    def __init__(self):
        self.removed = []

    def remove(self, image):
        self.removed.append(image)


@pytest.fixture
def images(monkeypatch):
    data = _Data()
    monkeypatch.setattr(capture.bpy, "data", SimpleNamespace(images=data))
    return data


def _scene(board=()):
    return SimpleNamespace(mixie_moodboard_images=list(board))


def test_a_superseded_still_is_freed(images):
    """Auto Key renders a fresh still per nudge; without this they pile up
    packed and orphaned in the saved file."""
    old = _Image()
    capture._discard_still(_scene(), old, SimpleNamespace(beats=[]))
    assert images.removed == [old]


def test_a_still_exported_to_the_moodboard_survives(images):
    old = _Image()
    board = [SimpleNamespace(image=old)]
    capture._discard_still(_scene(board), old, SimpleNamespace(beats=[]))
    assert images.removed == []


def test_a_still_another_beat_points_at_survives(images):
    old = _Image()
    shot = SimpleNamespace(beats=[SimpleNamespace(image=old)])
    capture._discard_still(_scene(), old, shot)
    assert images.removed == []


def test_a_still_with_users_survives(images):
    capture._discard_still(_scene(), _Image(users=1), SimpleNamespace(beats=[]))
    assert images.removed == []
