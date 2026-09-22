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
    letter_for = {"IMAGE": "I", "VIDEO": "V", "MESH": "M", "SPLAT": "S"}
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
    assert "socket_style::type_color" in painters
    # Empty sockets read hollow, connected ones have a pip, required rims are stronger.
    assert "occupied_inputs.contains" in draw
    assert 'RNA_boolean_get(&socket, "required")' in draw
    assert "if (connected)" in painters
    assert "required ? 1.8f : 1.25f" in painters
    # Selected nodes name their sockets.
    assert "moodboard_draw_socket_label" in draw


def test_socket_occupancy_comes_from_the_shared_cache():
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    header = _read(SPACE_MIXIE / "mixie_intern.hh")
    assert "occupied_inputs" in header
    assert "moodboard_graph_socket_key" in geometry
    assert "cache->occupied_inputs.add" in geometry


def test_socket_hit_and_qa_use_the_painters_shared_size_contract():
    hit_source = _read(SPACE_MIXIE / "mixie_moodboard_graph_hit.cc")
    hit = hit_source.split("static bool region_socket_hit(")[1].split("\n}")[0]
    assert "moodboard_socket_hit_radius_px(v2d, output)" in hit
    qa = _read(SPACE_MIXIE / "mixie_moodboard_qa_targets.cc")
    assert "moodboard_socket_hit_radius_px(hv2d, true)" in qa
    assert "moodboard_socket_hit_radius_px(v2d)" in qa


def test_media_without_a_graph_id_exposes_no_output():
    """A hit on id-less media would mint a link with an empty from_node_id."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_hit.cc")
    media_loop = geometry.split("bool moodboard_find_output_socket_under_mouse(")[1]
    assert "RNA_property_string_length(&item, id_prop) == 0" in media_loop


# --------------------------------------------------------------------------- #
# State hints and errors
# --------------------------------------------------------------------------- #


def test_running_nodes_never_draw_the_prompt_under_the_hint():
    """A selected QUEUED/RUNNING node drew a disabled prompt + Generate right
    over the centred "Generating..." text. Mid-flight the tile offers Cancel
    instead."""
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")
    assert "if (generation_running) {" in tile
    assert "MIXIE_OT_moodboard_cancel_action_node" in tile
    tail = tile.split("if (generation_running) {")[1]
    assert "else if (!has_result || state == 0 || edit_mode) {" in tail


def test_failed_hint_yields_to_the_visible_retry_controls():
    """With the floating prompt on screen the centred hint drew beneath it;
    the failure keeps its corner label and floats its reason above the card."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    assert "ELEM(state, 4, 5) && controls_visible" in draw
    # One definition of controls-visible, shared with the toolbar's gate.
    assert "moodboard_node_controls_rect(C, v2d, &node, &controls_rect)" in draw


def test_failed_nodes_show_their_error_message():
    """node.error was recorded and then shown nowhere."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    assert "draw_error_line" in draw
    assert "MIXIE_GRAPH_ERROR_BUF" in draw


def test_mesh_previews_stay_below_compact_settings_and_retry_controls():
    """Mesh result thumbnails must not paint over in-tile Settings or prompts."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    controls = node_ui.split("void mixie_draw_moodboard_graph_controls(")[1]
    assert controls.index("ui::icon_draw_preview(") < controls.index("ui::block_draw(C, block)")


def test_finished_nodes_offer_edit_and_run_again_in_settings():
    popup = _read(MOODBOARD / "ui/operators/node_settings_ops.py")
    assert 'text="Edit & Run Again"' in popup
    assert 'op.edit_before_run = True' in popup


def test_settings_entry_scales_with_the_ui_factor():
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC)" in node_ui
    assert "const int height = int(metrics.control_height)" in node_ui
    assert '"MIXIE_OT_moodboard_node_settings"' in node_ui


def test_a_finished_node_shows_its_result_behind_a_floating_edit_toggle():
    """The way back into a finished node used to be an "Edit & Run Again" row
    buried in the panel \u2014 only reachable once the panel was already open, and it
    reset the node's state to DRAFT (discarding its outcome and its error) just
    to make the prompt reappear. It is now a toggle floating over the card's
    top-right corner, and it changes nothing but how the card is presented.

    The panel row itself survives as the deliberate "start over" action, one
    level in; the toggle is the way back to the prompt."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")

    assert '"Edit & Run Again"' not in node_ui
    assert "edit_before_run" not in node_ui
    # A finished node draws the toggle and then stops: the panel below it is
    # the edit surface, and it is folded away until the toggle is on.
    assert "moodboard_add_node_card_actions(" in node_ui
    assert "if (!edit_mode) {" in node_ui
    # OUTSIDE the card: floating just above its top edge and right-aligned with
    # it, the same relationship the settings panel has to the card's left edge.
    # Laid over the card, these controls covered the result they belong to.
    assert "card.ymax + int(MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC)" in tile
    assert "int x = card.xmax - width" in tile
    assert "card.ymax - margin - height" not in tile
    # The header text is painted on this same row, so both must derive their
    # position from the same two constants or they land on different lines.
    chrome = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_chrome.cc")
    for metric in ("MOODBOARD_NODE_HEADER_LIFT", "MOODBOARD_NODE_HEADER_ROW_H"):
        assert metric in tile and metric in chrome, metric
    assert '"MIXIE_OT_moodboard_toggle_node_edit"' in tile
    # Icon buttons, not words: the row floats over the canvas above the card,
    # so it stays as small as a comfortable target allows. That makes the
    # tooltip the only text they carry.
    # While editing the toggle is a CANCEL, not a confirm: finishing an edit is
    # pressing Generate, which the open tile already offers, so a checkmark
    # would read as a second competing confirm beside it.
    assert "edit_mode ? ICON_X : ICON_GREASEPENCIL" in tile
    assert "ICON_CHECKMARK" not in tile
    assert "uiDefIconButO" in tile
    assert "const int width = height;" in tile, "icon buttons must stay square"

    # The operator is a pure presentation flip \u2014 it must not touch state, the
    # job, or the result.
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    toggle = ops.split("class MIXIE_OT_moodboard_toggle_node_edit")[1].split(
        "\nclass "
    )[0]
    assert "node.edit_mode = not node.edit_mode" in toggle
    for forbidden in ("node.state =", "node.job_id =", "node.preview_image ="):
        assert forbidden not in toggle


def test_the_card_action_row_stays_inside_the_painted_canvas():
    """Card actions use the painting surface except the drawer resize sash.
    The drawer's transparent tab gutter remains outside that surface; floating
    toolbars occlude content through draw order, not framing-margin clipping."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    assert "moodboard_canvas_controls_rect(C)" in node_ui
    layout = _read(SPACE_MIXIE / "mixie_moodboard_node_layout.cc")
    assert "rcti canvas = moodboard_canvas_draw_rect(area, region)" in layout
    assert "view3d_moodboard_drawer_edge_rect_for" in layout
    assert "edge.xmax - region->winrct.xmin + 1" in layout
    # Clip painting/input, without reflowing the card against the viewport edge.
    assert "ui::mixar_block_clip_set(block, clip)" in node_ui
    assert "canvas.ymax - height" not in tile
    # The name remains attached to the tile and shares the enclosing scissor.
    assert node_ui.index("mixie_draw_moodboard_selected_media_labels(") < node_ui.index(
        "GPU_scissor(previous_scissor")
    assert "region->winx" not in labels
    assert "region->winy" not in labels


def test_a_finished_node_can_export_its_own_result():
    """Export sits beside Edit on the card. It is scoped to THIS node, not the
    selection: the two usually coincide (clicking a card selects it) but with
    several cards selected the button on one card must save that card's
    result."""
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")

    assert '"MIXIE_OT_moodboard_export_images"' in tile
    export = tile.split('"MIXIE_OT_moodboard_export_images"')[1]
    # The exporter opens a file dialog, so it has to be invoked, not exec'd.
    assert "OpCallContext::InvokeDefault" in export
    assert (
        'RNA_string_set(ui::button_operator_ptr_ensure(save), "node_id", node_id)'
        in export
    )
    # Export claims the right-hand corner and Edit steps left of it, so Export
    # is laid out FIRST.
    assert tile.index("MIXIE_OT_moodboard_export_images") < tile.index(
        "MIXIE_OT_moodboard_toggle_node_edit"
    )
    # ICON_IMPORT, not ICON_EXPORT: the outward arrow reads as upload.
    assert "ICON_IMPORT," in tile
    assert "ICON_EXPORT," not in tile
    # Only when the result is MEDIA: a 3D result is a scene object, not a board
    # item the moodboard exporter can write. Export is now the first button laid
    # out, so the gate is a positive branch rather than an early return.
    assert "if (has_media_result) {" in tile
    assert "preview_ptr.data != nullptr" in node_ui

    # The operator honours that scoping instead of widening to the selection.
    ops = _read(MOODBOARD / "ui/operators/export_ops.py")
    assert "def _media_to_export(scene, node_id" in ops
    assert "return node_exportable_media(scene, node_id)" in ops
    assert "node_id: StringProperty(default=\"\", options={'SKIP_SAVE'})" in ops
    media = _read(MOODBOARD / "core/media_utils.py")
    assert "def node_exportable_media(scene, node_id" in media


def test_node_fields_retain_catalog_help_in_the_popup():
    settings = _read(MOODBOARD / "ui/operators/node_settings_ops.py")
    help_source = _read(MOODBOARD / "ui/operators/node_parameter_info.py")
    assert "info.details = parameter_help(parameter, spec)" in settings
    assert "return properties.details" in help_source


def test_a_result_can_be_opened_in_its_own_preview_window():
    """A card is a thumbnail sized for the graph, not for judging a result.
    Each press opens a NEW window -- nothing reuses or reclaims an existing one,
    which is what lets several results be compared side by side."""
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc")
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")

    assert "mixie_moodboard_ops_preview_window.cc" in cmake
    assert "WM_operatortype_append(MIXIE_OT_moodboard_preview_media)" in space

    # Built on the same primitive Blender's own render window uses; the context
    # moves to the new area, so the space to fill is CTX_wm_area afterwards.
    assert "WM_window_open(" in preview
    assert "SPACE_IMAGE" in preview
    assert "ED_space_image_set(bmain, sima, image, false)" in preview
    # Nothing looks for an existing preview to reuse -- that is the feature.
    assert "WM_window_find" not in preview

    # A movie needs its range and auto-refresh, or it sits on frame one.
    assert "IMA_ANIM_ALWAYS" in preview
    assert "IMA_SRC_MOVIE" in preview

    # REGISTER operator: a remembered id would preview the wrong card.
    assert "PROP_SKIP_SAVE" in preview.split("RNA_def_string(")[1]

    # The button sits between Edit and Export, and only when there is media.
    assert '"MIXIE_OT_moodboard_preview_media"' in tile
    assert "ICON_WINDOW" in tile
    assert tile.index("MIXIE_OT_moodboard_export_images") < tile.index(
        "MIXIE_OT_moodboard_preview_media"
    ) < tile.index("MIXIE_OT_moodboard_toggle_node_edit")
    assert "if (has_media_result) {" in tile


def test_sockets_name_themselves_while_a_noodle_is_in_flight():
    """Selection is no help mid-drag: the node being aimed at is usually not
    the selected one, and "what does this accept?" is exactly the question a
    drag raises."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    drag = _read(SPACE_MIXIE / "mixie_moodboard_graph_link_drag.cc")
    assert "moodboard_graph_link_drag_active(scene)" in draw
    assert "if ((selected || dragging_link) && radius >= 5 * UI_SCALE_FAC &&" in draw
    # The predicate reuses the drag state the preview noodle already keys on,
    # rather than tracking a second copy of "is a drag happening".
    assert "return link_drag_matches(scene);" in drag


def test_a_refused_connection_says_why_on_the_canvas():
    """`connect_nodes` already produces a specific sentence; it was going only
    to the status bar, which is not where the user is looking when they release
    a noodle."""
    chrome = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_chrome.cc")
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")

    assert "moodboard_draw_graph_notice(&scene_ptr)" in draw
    assert 'mixie_rna_string_get_clamped(scene_ptr, "mixie_moodboard_graph_notice"' in (
        chrome
    )
    assert "post_graph_notice(context.scene, str(exc), self.to_node_id)" in ops
    # Cleared by a one-shot timer, never by comparing a Python monotonic stamp
    # against Blender's: both are monotonic but their epochs differ.
    notice = _read(MOODBOARD / "core/graph_notice.py")
    assert "bpy.app.timers.register(_clear" in notice
    assert "BLI_time_now_seconds" not in chrome.split("moodboard_draw_graph_notice")[1]


def test_the_snap_grid_is_one_value_in_both_languages():
    """The C++ drags (nodes, media) and the Python grab modal move the same
    items, so two grids would snap them differently depending on the gesture."""
    header = _read(SPACE_MIXIE / "mixie_intern.hh")
    constants = _read(MOODBOARD / "constants.py")
    cpp = re.search(r"#define MOODBOARD_SNAP_GRID ([\d.]+)f", header)
    py = re.search(r"GRAPH_SNAP_GRID = ([\d.]+)", constants)
    assert cpp and py, "the snap grid is missing on one side"
    assert float(cpp.group(1)) == float(py.group(1))


def test_media_and_text_boxes_snap_too_not_just_nodes():
    """Snapping only nodes would make it impossible to line a node up against
    the reference image feeding it."""
    select = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    grab = _read(MOODBOARD / "ui/operators/transform_modal_ops.py")
    assert "event->modifier & KM_CTRL" in select
    assert "MOODBOARD_SNAP_GRID" in select
    assert "event.ctrl" in grab
    assert "GRAPH_SNAP_GRID" in grab
    # The GRABBED item snaps and the rest follow by the same delta, so a
    # multi-item selection keeps its spacing.
    assert "delta_x = snapped_x - move_data->initial_pos_x;" in select
    assert "self._initial_positions[0]" in grab


def test_holding_ctrl_snaps_a_dragged_node_to_the_canvas_grid():
    """The CARD's corner snaps, not the cursor: snapping the pointer would
    leave the card off-grid by wherever the user happened to grab it."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")
    assert "event->modifier & KM_CTRL" in ops
    assert "MOODBOARD_SNAP_GRID" in ops
    snap = ops.split("event->modifier & KM_CTRL")[1].split("}")[0]
    assert "std::round(new_x / grid) * grid" in snap
    assert "std::round(new_y / grid) * grid" in snap


def test_painted_canvas_text_carries_the_ui_factor():
    """Widget labels get UI_SCALE_FAC from the style; painted canvas text has to
    apply it itself. Without it every hint and the card header rendered at a
    fraction of the size of the buttons beside them on a high-DPI display."""
    graph = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    chrome = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_chrome.cc")

    assert "canvas_font_size(size)" in graph
    assert "size * UI_SCALE_FAC" in graph
    assert "BLF_size(font_id, size);" not in graph
    # The header measures the state text to reserve room for it and then draws
    # it; both calls must use the same size or the reservation is wrong.
    assert chrome.count("ui::mixar_text_style(ui::MixarTextRole::Caption, UI_SCALE_FAC)") == 2
    assert "BLF_size(font_id, 15.0f);" not in chrome


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


# --------------------------------------------------------------------------- #
# Selected media name
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #


def test_frame_selected_sits_with_select_all_and_names_its_shortcut():
    """Framing is otherwise reachable only by a key nobody has been told about.
    It goes in the selection group, but -- unlike Select All / Deselect All --
    it must NOT be hidden once an image is selected, which is exactly when it is
    wanted; it is disabled instead, so the shortcut beside it stays readable."""
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")

    assert '"mixie.moodboard_frame"' in menus
    entry = menus.split('"mixie.moodboard_frame"')[1][:300]
    assert "Frame Selected" in entry
    assert "Numpad ." in entry
    assert "frame.selected_only = True" in menus

    # Drawn outside the `selected_images == 0` branch that hides Select All.
    select_all_at = menus.index('"mixie.moodboard_select_all"')
    frame_at = menus.index('"mixie.moodboard_frame"')
    branch_at = menus.rindex("if selected_images == 0:", 0, select_all_at)
    assert branch_at < select_all_at < frame_at
    frame_row = menus[menus.rindex("frame_row = layout.row()", 0, frame_at):frame_at]
    assert "frame_row.enabled" in frame_row


def test_the_menus_shortcut_text_matches_the_real_binding():
    """The label is hand-written, so nothing but this stops it drifting from the
    keymap. Numpad Period is Blender's Frame Selected everywhere; the main-row
    period is a different key and must never be what gets bound."""
    space = _read(SPACE_MIXIE / "space_mixie.cc")

    assert "EVT_PADPERIOD" in space.split("frame_sel_params.type = ")[1][:40]
    assert 'RNA_boolean_set(kmi_frame_sel->ptr, "selected_only", true)' in space
    assert "EVT_PERIODKEY" not in space
