# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A moodboard drag moves the whole selection, whatever kinds it spans.

The board has ONE selection but TWO drag operators — `MIXIE_OT_moodboard_
select_image` for pictures and text, `MIXIE_OT_moodboard_graph_select` for
cards. Each used to move only its own kinds, so a picture and an inference node
selected together came apart under the mouse: the picture moved and the card
stood still. These are source-level pins — the modals only run inside a built
Blender — on the two halves of the fix: one shared capture of what a drag
carries, and a plain click that replaces the selection on BOTH sides so the
shared capture is never handed items the user thought they had deselected.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def _read(name: str) -> str:
    return (SPACE_MIXIE / name).read_text(encoding="utf-8")


def test_the_drag_set_covers_every_movable_kind():
    """The same four collections the Python grab (G) already moved together."""
    shared = _read("mixie_moodboard_move_selection.cc")
    grab = (MOODBOARD / "ui/operators/transform_modal_ops.py").read_text(
        encoding="utf-8"
    )
    for collection in (
        "mixie_moodboard_images",
        "mixie_moodboard_textboxes",
        "mixie_moodboard_action_nodes",
        "mixie_moodboard_asset_nodes",
    ):
        assert collection in shared, collection
        # G already moved a mixed selection correctly; the drag now matches it.
        assert collection in grab, collection


def test_both_drag_operators_move_through_the_shared_capture():
    """Neither modal may keep a private idea of what a drag carries."""
    graph = _read("mixie_moodboard_ops_graph.cc")
    media = _read("mixie_moodboard_ops_select.cc")

    # The card drag carries everything — other cards, pictures, text boxes.
    assert "moodboard_drag_set_capture(&scene_ptr, MOODBOARD_DRAG_ALL" in graph
    assert "moodboard_drag_set_apply(" in graph
    # Esc puts the whole set back, not just the card that was grabbed.
    assert "moodboard_drag_set_restore(&scene_ptr, data->drag)" in graph

    # The media drag carries the cards. It keeps its own image/text-box arrays
    # because those also drive resizing, which cards do not share.
    assert "MOODBOARD_DRAG_NODES, &move_data->node_drag)" in media
    assert "moodboard_drag_set_apply(&scene_ptr, move_data->node_drag" in media
    assert "moodboard_drag_set_restore(&scene_ptr, move_data->node_drag)" in media


def test_pressing_a_selected_card_keeps_the_selection():
    """Media's rule — "already selected, do nothing, allow drag" — on cards.

    `moodboard_graph_select_node` deselects the whole board before selecting.
    Running it on a card that was ALREADY selected wiped the rest of the
    selection before the drag could start, so a mixed selection could never
    survive being grabbed by its card.
    """
    graph = _read("mixie_moodboard_ops_graph.cc")
    invoke = graph.split("static wmOperatorStatus graph_select_invoke")[1]
    assert 'if (RNA_boolean_get(&node, "selected")) {' in invoke
    # The reselect is now the else branch, not unconditional.
    select_call = "moodboard_graph_select_node(&scene_ptr, kind, index, &node);"
    assert select_call in invoke
    assert invoke.index("else {") < invoke.index(select_call)


def test_a_plain_click_replaces_the_whole_board_selection():
    """`moodboard_deselect_all` only knows about media.

    The graph operator has always cleared both sides; the media one cleared
    only its own, leaving cards selected behind a click on a picture. Harmless
    while a media drag ignored cards — but once the drag carries them, such a
    card would travel with a click the user read as "just this image".
    """
    media = _read("mixie_moodboard_ops_select.cc")
    assert "static void moodboard_replace_selection(PointerRNA *scene_ptr)" in media
    # Every full-replace path goes through it; none clears media alone.
    for handler in (
        "handle_double_click_ungrouped_image",
        "handle_click_select_group",
        "handle_click_select_image",
    ):
        body = media.split(handler + "(MoodboardSelectionContext &ctx)\n{")[1].split(
            "\n}"
        )[0]
        assert "moodboard_replace_selection(ctx.scene_ptr)" in body, handler
        assert "moodboard_deselect_all(" not in body, handler

    # Box select selects cards, so its click-to-clear must clear them too.
    box = _read("mixie_moodboard_ops_box_select.cc")
    assert "moodboard_graph_deselect_nodes(&scene_ptr)" in box
