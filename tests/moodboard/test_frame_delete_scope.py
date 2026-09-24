# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A frame deletes its own contents and nothing else.

"Delete Frame and N Item(s)" routes through the board's own delete operator,
which acts on the WHOLE board's selection. Two ways that reached past the
frame: the selection was never cleared first, and a card's own generated
result could be counted as a member of a frame it merely sits inside.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _frames():
    from mixar.modules.moodboard.core import frames

    return frames


def _item(name, *, frame_id="", selected=False, embedded=""):
    return SimpleNamespace(
        name=name,
        frame_id=frame_id,
        selected=selected,
        embedded_node_id=embedded,
        node_id=name,
    )


def _scene(images=(), textboxes=()):
    return SimpleNamespace(
        mixie_moodboard_images=list(images),
        mixie_moodboard_textboxes=list(textboxes),
        mixie_moodboard_action_nodes=[],
        mixie_moodboard_asset_nodes=[],
        mixie_moodboard_frames=[],
    )


def test_a_cards_own_result_is_never_a_frames_member():
    """A generation result is placed on the board BEFORE it is marked
    node-owned, so it can pick up the frame id of whatever it landed in. Every
    other membership query already skips node-owned media; this one did not,
    so the result was counted, fitted around, and deleted with the frame."""
    frames = _frames()
    inside = _item("loose", frame_id="F")
    card_output = _item("result", frame_id="F", embedded="node-1")
    scene = _scene(images=[inside, card_output])

    members = frames.frame_members(scene, "F")

    assert inside in members
    assert card_output not in members, "a card's own output is not the frame's"


def test_membership_agrees_with_the_other_two_queries():
    """The bug was an inconsistency, not a missing feature: `selected_items`
    and `resolve_membership` already excluded node-owned media."""
    frames = _frames()
    card_output = _item("result", frame_id="F", embedded="node-1", selected=True)
    scene = _scene(images=[card_output])

    assert frames.frame_members(scene, "F") == []
    assert frames.selected_items(scene) == []


def test_placement_does_not_stamp_media_that_is_already_node_owned():
    source = (MOODBOARD / "core/moodboard_utils.py").read_text(encoding="utf-8")
    adopt = source.split("def _adopt_into_frame(")[1].split("\ndef ")[0]

    assert "_is_node_owned" in adopt, "node-owned media is not a frame's to adopt"
    assert adopt.index("if _is_node_owned(item):") < adopt.index("item.frame_id = frame_id")


def test_deleting_a_frame_clears_the_rest_of_the_board_first():
    """`select_frame_contents` only ADDS to the selection and
    `mixie.moodboard_delete` acts on the whole board, so anything selected
    elsewhere was destroyed too -- past what the button's own label promises.

    Pinned at source level: the operator is a `bpy.types.Operator` subclass,
    which is a MagicMock in this suite.
    """
    source = (MOODBOARD / "ui/operators/frame_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "MIXIE_OT_moodboard_delete_frame"
    )
    execute = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "execute"
    )
    body = ast.unparse(execute)

    deselect = body.index("deselect_all_frames")
    select_contents = body.index("select_frame_contents")
    delete = body.index("mixie.moodboard_delete")

    assert deselect < select_contents < delete, (
        "the board must be cleared before the frame's members are selected"
    )
    assert "item.selected = False" in body, "items selected elsewhere stay selected"
