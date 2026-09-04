# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo takes back what the user DREW, and never what the freeze still holds.

Two failures with one shape — something released a mark's belongings while
another party still referenced them:

* ``remove_last`` popped the newest collection item with no state check, so
  one Backspace on a freshly armed freeze deleted a mark from the PREVIOUS
  turn (and its vertex group) while the pill still read zero. Marks are kept
  after send precisely because the next turn refers back to them.
* Undoing the only mark of the LIVE freeze released that freeze's baked
  camera, because no other mark named it — but the freeze does, and the next
  mark is drawn against it. ``FreezeSession`` also went on believing its view
  was in use, so disarming leaked the packed still into the .blend.
"""

import pathlib

import pytest

from mixar.modules.scribble_mark.core import marks as mark_store


REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "src/scripts/mixar/modules/scribble_mark"


def source(path):
    return (MODULE / path).read_text()


class _Item:
    def __init__(self, serial, state="DRAFT", view_name=""):
        self.serial = serial
        self.state = state
        self.mark_json = "{}"
        self.view_name = view_name


class _Collection(list):
    """Blender collection semantics: ``remove`` takes an INDEX, not a value."""

    def remove(self, index):
        del self[index]


class _Scene:
    def __init__(self, items):
        self.mixar_marks = _Collection(items)


@pytest.fixture
def released(monkeypatch):
    """Record every camera ``_release_item`` gives back."""
    names = []

    class _Bake:
        @staticmethod
        def release(name):
            names.append(name)

    monkeypatch.setattr(mark_store, "view_bake", _Bake)
    return names


# =============================================================================
# A sent mark is not undoable
# =============================================================================

class TestUndoTakesBackDraftsOnly:
    def test_the_newest_draft_goes_not_the_newest_item(self, released):
        scene = _Scene([_Item(1, "SENT"), _Item(2, "DRAFT")])
        assert mark_store.remove_last(scene) is True
        assert [i.serial for i in scene.mixar_marks] == [1]

    def test_a_fully_sent_turn_has_nothing_to_undo(self, released):
        scene = _Scene([_Item(1, "SENT"), _Item(2, "SENT")])
        assert mark_store.remove_last(scene) is False
        assert [i.serial for i in scene.mixar_marks] == [1, 2], (
            "the conversation still refers to these"
        )
        assert released == [], "and nothing they own may be given back"

    def test_an_empty_scene_is_a_no_op(self, released):
        assert mark_store.remove_last(_Scene([])) is False

    def test_clear_discards_the_queued_marks_only(self, released):
        scene = _Scene([_Item(1, "SENT", "v3"), _Item(2, "DRAFT", "v7")])
        assert mark_store.clear(scene, drafts_only=True) == 1
        assert [i.serial for i in scene.mixar_marks] == [1]
        assert released == ["v7"], "the sent mark keeps its camera"

    def test_clear_keeps_the_frame_while_a_sent_mark_still_names_it(self, monkeypatch):
        gone = []

        class _Freeze:
            @staticmethod
            def release(name):
                gone.append(name)

        monkeypatch.setattr(mark_store, "freeze", _Freeze)
        monkeypatch.setattr(mark_store, "view_bake", type("_B", (), {
            "release": staticmethod(lambda name: None)}))
        scene = _Scene([_Item(1, "SENT"), _Item(2, "DRAFT")])
        scene.mixar_mark_frame_name = "mixar_mark_frame_0007"
        mark_store.clear(scene, drafts_only=True)
        assert gone == [], "a sent mark still describes that frame"

        mark_store.clear(scene)
        assert gone == ["mixar_mark_frame_0007"], (
            "with no mark left the still is unreferenced"
        )

    def test_the_clear_operator_and_its_surfaces_agree_on_drafts(self):
        text = source("ui/operators/mark_arm_ops.py")
        clear = text[text.index("class MIXAR_OT_scribble_mark_clear"):]
        assert clear.count("drafts_only=True") == 2, (
            "both the poll and the execute must be draft-scoped — the chip "
            "shows the DRAFT count and its tooltip says 'queued'"
        )

    def test_the_header_undo_polls_drafts_only(self):
        text = source("ui/operators/mark_arm_ops.py")
        undo = text[text.index("class MIXAR_OT_scribble_mark_undo"):]
        undo = undo[:undo.index("class MIXAR_OT_scribble_mark_clear")]
        assert "drafts_only=True" in undo, (
            "a poll counting SENT marks arms a button that deletes one"
        )


# =============================================================================
# The live freeze keeps its camera
# =============================================================================

class TestUndoKeepsTheLiveFreeze:
    def test_the_live_view_is_never_released(self, released):
        scene = _Scene([_Item(1, "DRAFT", "mixar_mark_view_0007")])
        mark_store.remove_last(scene, keep_view="mixar_mark_view_0007")
        assert released == [], "the next mark is drawn against this camera"

    def test_a_stale_view_no_mark_shares_is_released(self, released):
        scene = _Scene([_Item(1, "DRAFT", "mixar_mark_view_0003")])
        mark_store.remove_last(scene, keep_view="mixar_mark_view_0007")
        assert released == ["mixar_mark_view_0003"]

    def test_a_view_a_sibling_still_names_is_kept(self, released):
        scene = _Scene([
            _Item(1, "DRAFT", "mixar_mark_view_0003"),
            _Item(2, "DRAFT", "mixar_mark_view_0003"),
        ])
        mark_store.remove_last(scene)
        assert released == []

    def test_view_referenced_reads_the_remaining_marks(self):
        scene = _Scene([_Item(1, "SENT", "v7"), _Item(2, "DRAFT", "v9")])
        assert mark_store.view_referenced(scene, "v7") is True
        assert mark_store.view_referenced(scene, "v3") is False
        assert mark_store.view_referenced(scene, "") is False

    def test_the_modal_hands_its_view_over_and_re_reads_view_used(self):
        text = source("ui/operators/mark_draw_ops.py")
        undo = text[text.index("def _undo_last"):]
        undo = undo[:undo.index("def _flip_reading")]
        assert "keep_view=self._session.view_name" in undo, (
            "the live freeze's camera must survive its last mark"
        )
        assert "view_used" in undo and "view_referenced" in undo, (
            "and the freeze must learn it is unreferenced again, or "
            "release_if_unused leaves the packed still in the .blend"
        )

    def test_the_header_undo_spares_a_live_freeze_too(self):
        text = source("ui/operators/mark_arm_ops.py")
        assert "keep_view=_live_view_name()" in text
        assert "def live_view_name" in source("ui/operators/mark_draw_ops.py")
