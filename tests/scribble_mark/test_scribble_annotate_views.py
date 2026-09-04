# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The annotated frame only carries the ink drawn on IT.

A freeze mints its frame image and its baked camera from one serial, and a
mark names the camera it was drawn under. When the mode is re-armed — or the
viewport resizes mid-mode — the drafts of the earlier freeze describe a
different camera and framing. Converting their normalized strokes against
this frame's size would ink them where the user never drew, on the one
picture the agent is told shows the marks, so ``_attach_frames`` draws only
the marks whose view matches the attached frame.
"""

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))
for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

import pytest  # noqa: E402

from mixar.modules.scribble_mark.core import chat_bridge, view_bake  # noqa: E402


VIEW_CURRENT = "mixar_mark_view_0007"
VIEW_OLDER = "mixar_mark_view_0003"
FRAME_CURRENT = "mixar_mark_frame_0007"


def _mark(mark_id, view, strokes=None):
    return {
        "id": mark_id,
        "view": view,
        "gesture": "circle",
        "closed": True,
        "strokes": strokes if strokes is not None else [[[0.1, 0.1], [0.9, 0.9]]],
        "region": {"bbox": [0.1, 0.1, 0.9, 0.9], "polygon": [], "anchor": None},
    }


class FakeAttachments:
    """Duck-typed pending-attachments collection property."""

    def __init__(self):
        self._items = []

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def add(self):
        item = MagicMock()
        self._items.append(item)
        return item


class FakeScene:
    def __init__(self, frame_name=FRAME_CURRENT):
        self.mixar_mark_frame_name = frame_name
        self.mixie_chat_pending_attachments = FakeAttachments()


@pytest.fixture
def seams(monkeypatch):
    """Stub the bpy-adjacent seams and record what the annotator received."""
    recorded = {}

    def get_image(name):
        return MagicMock(name=f"image:{name}")

    def render_annotated(image, marks, name):
        recorded["marks"] = list(marks)
        recorded["name"] = name
        return "annotated_image"

    monkeypatch.setattr(chat_bridge.freeze, "get_image", get_image)
    monkeypatch.setattr(
        chat_bridge.annotate, "render_annotated", render_annotated
    )
    return recorded


def test_the_frame_serial_mints_its_view_name():
    assert view_bake.view_name_for_frame("mixar_mark_frame_0007") == VIEW_CURRENT
    assert view_bake.view_name_for_frame("mixar_mark_frame_0") == \
        "mixar_mark_view_0000"
    assert view_bake.view_name_for_frame("") is None
    assert view_bake.view_name_for_frame("mixar_mark_frame") is None


def test_marks_from_the_frame_view_are_annotated(seams, monkeypatch):
    current = _mark(7, VIEW_CURRENT)
    older = _mark(3, VIEW_OLDER)
    monkeypatch.setattr(
        chat_bridge.mark_store, "draft_marks", lambda scene: [current, older]
    )
    notes = chat_bridge._attach_frames(FakeScene(), {"marks": [current, older]})

    assert seams["marks"] == [current]
    assert any("1 earlier mark" in note for note in notes)


def test_every_mark_on_its_own_frame_annotates_normally(seams, monkeypatch):
    only = _mark(7, VIEW_CURRENT)
    monkeypatch.setattr(
        chat_bridge.mark_store, "draft_marks", lambda scene: [only]
    )
    notes = chat_bridge._attach_frames(FakeScene(), {"marks": [only]})

    assert seams["marks"] == [only]
    assert not any("earlier mark" in note for note in notes)


def test_an_older_freeze_frame_skips_foreign_ink(seams, monkeypatch):
    """Sending while only older-freeze drafts exist: no annotation is queued
    (it would duplicate the clean frame) and the note says so."""
    older = _mark(3, VIEW_OLDER)
    monkeypatch.setattr(
        chat_bridge.mark_store, "draft_marks", lambda scene: [older]
    )
    scene = FakeScene()
    notes = chat_bridge._attach_frames(scene, {"marks": [older]})

    attached = [a.display_name for a in scene.mixie_chat_pending_attachments]
    assert "annotated_image" not in attached
    assert any("carries none of the marks" in note for note in notes)
    # The clean frame still travels.
    assert FRAME_CURRENT in attached


def test_wire_marks_without_drafts_are_filtered_too(seams, monkeypatch):
    """The wire fallback (stored records gone) still respects the view gate."""
    current = _mark(7, VIEW_CURRENT)
    current.pop("strokes")  # the wire payload leaves the raw strokes behind
    older = _mark(3, VIEW_OLDER)
    monkeypatch.setattr(
        chat_bridge.mark_store, "draft_marks", lambda scene: []
    )
    chat_bridge._attach_frames(FakeScene(), {"marks": [current, older]})

    assert seams["marks"] == [current]
