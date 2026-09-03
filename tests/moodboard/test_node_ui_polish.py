# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Node canvas polish contracts: sockets, hints, cancel, and draw cost.

The behaviours live in compiled C++ draw/hit-test code, so most pins are
source-level; the cross-language tables are checked value-for-value.
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Sockets
# --------------------------------------------------------------------------- #


def test_output_handle_colors_match_the_python_output_types():
    """The C++ per-action output color table is ORDER-PINNED to ACTION_TYPES.

    Blender persists the enum as an index, so the C++ table is indexed the same
    way — a reorder or append in Python must be mirrored here or a node's
    output handle lies about its type.
    """
    from mixar.modules.moodboard.core.node_schema import _OUTPUT_TYPES
    from mixar.modules.moodboard.ui.moodboard_graph_properties import ACTION_TYPES

    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_sockets.cc")
    match = re.search(r"ACTION_OUTPUT_KINDS\[\]\s*=\s*\{([^}]*)\}", draw)
    assert match, "the C++ output-kind table is missing"
    kinds = re.findall(r"'(\w)'", match.group(1))
    assert len(kinds) == len(ACTION_TYPES), (
        "the C++ output-kind table and ACTION_TYPES disagree on length"
    )
    letter_for = {"IMAGE": "I", "VIDEO": "V", "MESH": "M"}
    for index, (identifier, *_rest) in enumerate(ACTION_TYPES):
        expected = letter_for[_OUTPUT_TYPES[identifier]]
        assert kinds[index] == expected, (
            f"ACTION_TYPES[{index}]={identifier} outputs {_OUTPUT_TYPES[identifier]} "
            f"but the C++ table says '{kinds[index]}'"
        )


def test_sockets_draw_type_color_occupancy_and_labels():
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    painters = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_sockets.cc")
    # Type-colored from the socket's own accepted_types — data-driven, so an
    # unknown future type degrades to neutral rather than misreporting.
    assert "moodboard_socket_type_color(" in draw
    assert '"accepted_types"' in draw
    assert "SOCKET_COLOR_NEUTRAL" in painters
    # Empty sockets read hollow, connected ones filled, required ones louder.
    assert "occupied_inputs.contains" in draw
    assert 'RNA_boolean_get(&socket, "required")' in draw
    assert "imm_draw_circle_wire_2d" in painters
    # Selected nodes name their sockets.
    assert "moodboard_draw_socket_label" in draw


def test_socket_occupancy_comes_from_the_shared_cache():
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    header = _read(SPACE_MIXIE / "mixie_intern.hh")
    assert "occupied_inputs" in header
    assert "moodboard_graph_socket_key" in geometry
    assert "cache->occupied_inputs.add" in geometry


def test_socket_hit_radius_follows_the_view_scale():
    """The drawn socket zooms (canvas units); a fixed pixel hit radius left a
    zoomed-in socket's rim unclickable."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    hit = geometry.split("static bool region_socket_hit(")[1].split("\n}")[0]
    # Blender 5.2: the C API wrapper was renamed to the ui:: namespace.
    assert "ui::view2d_scale_get_x" in hit
    assert "MOODBOARD_GRAPH_SOCKET_RADIUS * scale" in hit


def test_media_without_a_graph_id_exposes_no_output():
    """A hit on id-less media would mint a link with an empty from_node_id."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    media_loop = geometry.split("bool moodboard_find_output_socket_under_mouse(")[1]
    assert "RNA_property_string_length(&item, id_prop) == 0" in media_loop


# --------------------------------------------------------------------------- #
# State hints and errors
# --------------------------------------------------------------------------- #


def test_running_nodes_never_draw_the_prompt_under_the_hint():
    """A selected QUEUED/RUNNING node drew a disabled prompt + Generate right
    over the centred "Generating..." text. Mid-flight the tile offers Cancel
    instead."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "if (generation_running) {" in node_ui
    assert "MIXIE_OT_moodboard_cancel_action_node" in node_ui
    tail = node_ui.split("if (generation_running) {")[1]
    assert "else if (!has_result || state == 0) {" in tail


def test_failed_hint_yields_to_the_visible_retry_controls():
    """With the floating prompt on screen the centred hint drew beneath it;
    the failure keeps its corner label and floats its reason above the card."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    assert "ELEM(state, 4, 5) && controls_visible" in draw
    # One definition of controls-visible, shared with the toolbar's gate.
    assert draw.count("MOODBOARD_GRAPH_CONTROLS_MIN_PX_X") == 1


def test_failed_nodes_show_their_error_message():
    """node.error was recorded and then shown nowhere."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    assert "draw_error_line" in draw
    assert "MIXIE_GRAPH_ERROR_BUF" in draw


def test_finished_nodes_offer_edit_and_run_again_on_the_panel():
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "show_rerun" in node_ui
    assert '"Edit & Run Again"' in node_ui
    # Blender 5.2: operator properties are set through
    # ui::button_operator_ptr_ensure (no separate rerun_props handle).
    assert (
        'RNA_boolean_set(ui::button_operator_ptr_ensure(rerun), "edit_before_run", true)'
        in node_ui
    )


def test_node_panel_metrics_scale_with_the_ui_factor():
    """Labels render at UI_SCALE_FAC; fixed pixel rows clipped them on high-DPI."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "const int row_h = int(32 * ui_scale)" in node_ui
    assert "const int panel_width = int(244 * ui_scale)" in node_ui


# --------------------------------------------------------------------------- #
# Interaction
# --------------------------------------------------------------------------- #


def test_node_move_applies_the_shared_drag_threshold():
    """A click that wobbles a pixel is a click, not a request to nudge the card."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")
    move_branch = ops.split("if (data->link_drag) {")[1].split("graph_select_cancel")[0]
    # After the link-drag block, the node-move MOUSEMOVE branch gates on the
    # same threshold constant before writing positions.
    node_move = move_branch.split("graph_node_pointer(&scene_ptr, data->kind")[1]
    assert "MOODBOARD_DRAG_THRESHOLD_PX" in node_move
    assert "if (!data->moved)" in node_move


def test_shift_click_toggles_graph_cards_in_the_selection():
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")
    assert 'RNA_boolean_get(op->ptr, "extend")' in ops
    assert 'RNA_def_boolean(ot->srna,\n                  "extend"' in ops or '"extend"' in ops
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    # The graph item is added BEFORE the media item for the same shift binding,
    # so cards get first refusal and everything else passes through to media.
    graph_at = space.find('"MIXIE_OT_moodboard_graph_select", &params_extend)')
    media_at = space.find('"MIXIE_OT_moodboard_select_image", &params_extend)')
    assert 0 <= graph_at < media_at


def test_cancel_operator_reaches_the_queue_and_the_menu():
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    assert '"mixie.moodboard_cancel_action_node"' in ops
    bridge = _read(MOODBOARD / "core/node_job_bridge.py")
    # Cancelled by graph_node_id across every queue: the node's stored job_id
    # flips to the backend id mid-flight, so it cannot address the queue.
    assert "def cancel_node_job(" in bridge
    assert "graph_node_id" in bridge.split("def find_active_node_job(")[1]
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")
    assert "mixie.moodboard_cancel_action_node" in menus
    # Deleting a node cancels the job that could no longer deliver into it.
    deletion = _read(MOODBOARD / "core/node_deletion.py")
    assert "cancel_node_job" in deletion


# --------------------------------------------------------------------------- #
# Draw cost
# --------------------------------------------------------------------------- #


def test_pulse_timer_is_capped_at_fifteen_fps():
    """The glow breathes over ~2.9s; 30 fps full-canvas repaints doubled the
    draw cost of every generating session for no visible gain.

    Source-level: importing node_job_bridge drags in the job_queue runtime.
    """
    bridge = _read(MOODBOARD / "core/node_job_bridge.py")
    match = re.search(
        r"_PULSE_INTERVAL_S\s*=\s*1\.0\s*/\s*(\d+(?:\.\d+)?)", bridge
    )
    assert match, "_PULSE_INTERVAL_S must stay a 1/fps literal"
    assert float(match.group(1)) <= 15.0 + 1e-9
