# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Playback contracts for movies rendered inside an inference node.

A generated video is owned by its node (``embedded_node_id``), which excludes
it from the standalone-tile hit-test. Every seam that made an uploaded movie
playable therefore needs an explicit node-aware counterpart; the compiled
canvas cannot be exercised outside Blender, so these are source-level pins.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_node_owned_media_is_still_hidden_from_the_standalone_tile_hit_test():
    """The premise of the bug. If this stops being true the node-aware paths
    below are redundant, not merely unused."""
    select = _read(SPACE_MIXIE / "mixie_select.cc")

    lookup = select.split("int moodboard_find_image_under_mouse(")[1]
    assert "embedded_node_id" in lookup


def test_node_preview_movies_draw_the_play_affordance():
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")

    assert "IMA_SRC_MOVIE" in draw
    assert "moodboard_video_playback_frame" in draw
    assert "mixie_draw_moodboard_video_overlay" in draw
    # The overlay is shared with standalone tiles, not reimplemented.
    images = _read(SPACE_MIXIE / "mixie_draw_moodboard_images.cc")
    assert "void mixie_draw_moodboard_video_overlay(" in images


def test_clicking_a_node_preview_toggles_playback_before_the_move_modal():
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")

    invoke = ops.split("static wmOperatorStatus graph_select_invoke(")[1]
    toggle_at = invoke.find("moodboard_toggle_video_playback")
    modal_at = invoke.find("WM_event_add_modal_handler(C, op);\n  return OPERATOR_RUNNING_MODAL")
    assert toggle_at != -1, "node previews never reach the playback toggle"
    # The node-move branch has no drag threshold, so it would slide the card on
    # the first mouse-move of the very click that started playback.
    assert modal_at == -1 or toggle_at < modal_at
    assert "MOODBOARD_VIDEO_PLAY_RADIUS_PX" in invoke
    assert "KM_DBL_CLICK" in invoke


def test_asset_double_click_still_selects_objects_rather_than_playing():
    """Both node kinds share the click path; the play branch must not swallow
    the asset card's double-click."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")

    invoke = ops.split("static wmOperatorStatus graph_select_invoke(")[1]
    asset_branch = invoke.find("MIXIE_OT_moodboard_select_asset_objects")
    play_branch = invoke.find("moodboard_toggle_video_playback")
    assert asset_branch != -1 and play_branch != -1
    assert "if (kind == GRAPH_ASSET)" in invoke
    assert asset_branch < play_branch


def test_hover_monitor_recognizes_node_previews():
    """It compares the hovered index against ``playback.item_index`` and stops
    anything else, so a node preview it cannot see stops on the first move."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    hover = preview.split("static int hovered_video_index_from_event(")[1]
    assert "moodboard_find_node_preview_video_under_mouse" in hover


def test_node_preview_resolver_returns_a_media_index_not_a_node_index():
    """``moodboard_toggle_video_playback`` and the hover monitor both key on an
    index into ``mixie_moodboard_images``; a node index would silently
    mismatch."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")

    resolver = geometry.split("int moodboard_find_node_preview_video_under_mouse(")[1]
    assert "moodboard_find_embedded_media_index" in resolver
    assert "moodboard_item_is_video(scene_ptr, media_index)" in resolver
    assert "return media_index;" in resolver


def test_preview_bounds_have_a_single_definition():
    """The play button's pixels and its click region are derived from this; two
    copies of the inset would let them drift apart silently."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    header = _read(SPACE_MIXIE / "mixie_intern.hh")

    assert "void moodboard_graph_node_preview_bounds(" in geometry
    assert "MOODBOARD_GRAPH_PREVIEW_INSET" in header
    assert "moodboard_graph_node_preview_bounds(rect, &preview_bounds)" in draw


def test_playback_state_is_pruned_against_main():
    """Node deletion frees the generated movie it owns, so an entry keyed on
    the freed Image would be inherited by a datablock reusing that address."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "prune_dead_playback_entries" in preview
    assert "BLI_findindex(&bmain->images" in preview
    assert "prune_dead_playback_entries(C);" in preview


def test_export_reaches_media_owned_by_a_selected_node():
    """Right-clicking a completed node and choosing Export used to be greyed
    out: the result is never ``selected`` itself, so both the menu gate and the
    operator's own lookup saw an empty selection."""
    media_utils = _read(MOODBOARD / "core/media_utils.py")
    export_ops = _read(MOODBOARD / "ui/operators/export_ops.py")
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")

    assert "def selected_exportable_media(scene)" in media_utils
    # One definition, shared by the gate and the operator — a second copy would
    # let the row's enabled state and the operator's result diverge.
    assert "selected_exportable_media" in export_ops
    assert "selected_exportable_media" in menus
    assert "row.enabled = bool(exportable_media)" in menus

    resolver = media_utils.split("def selected_exportable_media(scene)")[1].split("\ndef ")[0]
    assert "mixie_moodboard_action_nodes" in resolver
    assert "embedded_node_id" in resolver


def test_in_place_edits_stay_keyed_on_direct_selection():
    """Crop/rotate/flip must NOT pick up node-owned results: editing a result
    in place would desynchronise it from the node that produced it."""
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")

    for operator in (
        "mixie.moodboard_crop_tool",
        "mixie.rotate_images",
        "mixie.flip_horizontal",
        "mixie.flip_vertical",
    ):
        before = menus.split(operator)[0]
        gate = before.rstrip().rsplit("row.enabled = ", 1)[1].splitlines()[0]
        assert "exportable_media" not in gate, f"{operator} must not use the export set"
