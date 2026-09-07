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
    assert "UI_view2d_scale_get_x" in hit
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
    # ONE definition of controls-visible, shared with the toolbar's own gate.
    # The panel is canvas content that shrinks with its card rather than
    # vanishing below a pixel threshold, so selection alone decides.
    assert draw.count("const bool controls_visible = selected;") == 1
    assert "MOODBOARD_GRAPH_CONTROLS_MIN_PX" not in draw


def test_failed_nodes_show_their_error_message():
    """node.error was recorded and then shown nowhere."""
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    assert "draw_error_line" in draw
    assert "MIXIE_GRAPH_ERROR_BUF" in draw


def test_a_finished_node_shows_its_result_behind_a_floating_edit_toggle():
    """The way back into a finished node used to be an "Edit & Run Again" row
    buried in the panel — only reachable once the panel was already open, and it
    reset the node's state to DRAFT (discarding its outcome and its error) just
    to make the prompt reappear. It is now a toggle floating over the card's
    top-right corner, and it changes nothing but how the card is presented."""
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
    assert "node_rect.ymax + MOODBOARD_NODE_HEADER_LIFT" in tile
    assert "int(node_rect.xmax) - width" in tile
    assert "int(node_rect.ymax) - margin - height" not in tile
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

    # The operator is a pure presentation flip — it must not touch state, the
    # job, or the result.
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    toggle = ops.split("class MIXIE_OT_moodboard_toggle_node_edit")[1].split(
        "\nclass "
    )[0]
    assert "node.edit_mode = not node.edit_mode" in toggle
    for forbidden in ("node.state =", "node.job_id =", "node.preview_image ="):
        assert forbidden not in toggle


def test_node_panel_metrics_scale_with_the_ui_factor():
    """Labels render at UI_SCALE_FAC; fixed pixel rows clipped them on high-DPI.

    The VERTICAL metrics (rows, insets, gaps) exist to fit text and so stay
    tied to the UI factor.
    """
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "const int inset = int(14 * ui_scale)" in node_ui
    assert "const int gap = int(6 * ui_scale)" in node_ui
    # The row height is negotiated against the card (see the height test) but
    # both of its clamps are still DPI-derived, so text can never be crushed.
    assert "int(MOODBOARD_NODE_PANEL_MIN_ROW_H * ui_scale)" in node_ui
    assert "int(32 * ui_scale));" in node_ui


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
    assert 'RNA_string_set(UI_but_operator_ptr_ensure(save), "node_id", node_id)' in (
        export
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


def test_node_fields_carry_their_own_tooltips():
    """The panel's fields draw their VALUE, not their name -- a dropdown reads
    "1K", a number field just "1" -- so the tooltip is the only thing that says
    what a field is. It cannot come from RNA: every catalog parameter shares one
    set of value properties, so uiDefButR's fallback to the property description
    would put identical text on every field of every node."""
    tooltips = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tooltips.cc")
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")

    # uiBut::tip is a NON-owning StringRef, so a locally built string would
    # dangle: the button outlives the draw and is what the tooltip is read from.
    # The button must own a copy and free it.
    assert "UI_but_func_tooltip_set(but, node_tooltip_func, BLI_strdup(text), MEM_freeN)" in (
        tooltips
    )
    # Composed from the parameter's OWN catalog text, plus the bounds a plain
    # number field cannot show.
    assert 'mixie_rna_string_get_clamped(parameter, "label"' in tooltips
    assert 'mixie_rna_string_get_clamped(parameter, "description"' in tooltips
    assert '"Range: "' in tooltips
    # Every field the panel draws is covered.
    assert "moodboard_set_parameter_tooltip(button, parameter)" in node_ui
    assert "moodboard_set_node_tooltip(mode," in node_ui
    assert "moodboard_set_node_tooltip(model," in node_ui


def test_node_panel_width_follows_the_card_not_the_ui_factor():
    """A DPI-scaled constant width crept up on the card's own (DPI-independent)
    width, so on a high-DPI display the settings panel was nearly as wide as the
    node it configures. It is a fraction of the card, floored at what a model
    name needs so labels can still never clip."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "const int panel_width = int(244 * ui_scale)" not in node_ui
    assert "BLI_rctf_size_x(&node_rect) * MOODBOARD_NODE_PANEL_WIDTH_RATIO" in node_ui
    assert "MOODBOARD_NODE_PANEL_MIN_TEXT_W * ui_scale" in node_ui


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
    node_id = preview.split('"node_id"')[1]
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
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    assert "moodboard_graph_link_drag_active(scene)" in draw
    assert "if ((selected || dragging_link) && socket_labels_readable) {" in draw
    # The predicate reuses the drag state the preview noodle already keys on,
    # rather than tracking a second copy of "is a drag happening".
    assert "return link_drag_matches(scene);" in geometry


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
    assert chrome.count("BLF_size(font_id, 15.0f * UI_SCALE_FAC);") == 2
    assert "BLF_size(font_id, 15.0f);" not in chrome


def test_node_panel_height_follows_the_card_too():
    """Half the card in BOTH axes. Height is reached by sizing the rows to the
    target, not by stretching or clipping the panel: the fixed chrome comes off
    first and the remainder is shared between the control rows and Reset. A
    content-driven height alone left the panel as tall as the card it sits
    beside."""
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    assert "BLI_rctf_size_y(&node_rect) *" in node_ui
    assert "MOODBOARD_NODE_PANEL_HEIGHT_RATIO" in node_ui
    assert "const int panel_height = chrome + rows * row_h;" in node_ui
    # `rows` and `chrome` must together describe exactly what the layout draws
    # below, or the panel background and its contents disagree.
    assert "const int rows = control_count + 1;" in node_ui
    assert (
        "const int chrome = inset * 2 + (control_count - 1) * gap + reset_gap;"
        in node_ui
    )


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


def test_selected_media_shows_its_name_not_a_hovering_bubble():
    """The selection used to raise a rounded "Image"/"Video" bubble over the
    canvas — chrome that covered part of the board to repeat what the picture
    already said. The one thing the tile cannot show is WHICH file it is, so
    that slot carries the media's own name instead, as plain small text with no
    background of its own."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    assert "image->id.name + 2" in labels
    assert "moodboard_draw_floating_background" not in labels
    assert "uiDefBut" not in labels
    assert '"Video" : "Image"' not in labels
    # Painted text, so it takes no uiBlock at all.
    assert "uiBlock" not in labels
    assert "BLF_draw(" in labels
    # The name is sized WITH the canvas, not pinned to a constant screen size.
    # Pinned, a zoomed-out 111px tile wore a 126px name -- text wider than the
    # picture it labelled. So the point size carries the DPI factor AND the
    # View2D scale.
    assert "MOODBOARD_MEDIA_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale" in labels
    assert "UI_view2d_scale_get_x(v2d)" in labels
    size = re.search(
        r"#define MOODBOARD_MEDIA_LABEL_SIZE_PX (\d+(?:\.\d+)?)f", labels
    )
    assert size, "the point size must stay a named constant"
    assert float(size.group(1)) <= 12.0


def test_a_media_name_never_outgrows_the_tile_it_labels():
    """Scaling by zoom alone is not enough: a tile's width is its OWN canvas
    size times the zoom, so a user-shrunk image at a high zoom would still wear
    an oversized name. The size is fitted to the tile, floored for legibility,
    and dropped outright when the tile is too narrow to carry a readable name
    -- clamping up without the fit is what puts a name wider than its picture
    back on screen."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    for macro in (
        "MOODBOARD_MEDIA_LABEL_MIN_PX",
        "MOODBOARD_MEDIA_LABEL_MAX_PX",
    ):
        assert re.search(rf"#define {macro} (\d+(?:\.\d+)?)f", labels), macro
    floor = float(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MIN_PX (\d+(?:\.\d+)?)f", labels).group(1)
    )
    ceiling = float(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_PX (\d+(?:\.\d+)?)f", labels).group(1)
    )
    assert 0.0 < floor < ceiling

    # Floor first (a pulled-back canvas keeps its names), then fit to the tile.
    assert "std::clamp(MOODBOARD_MEDIA_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale" in labels
    assert "font_px *= tile_width / text_width;" in labels
    fit_at = labels.index("font_px *= tile_width / text_width;")
    drop_at = labels.index("if (font_px < MOODBOARD_MEDIA_LABEL_MIN_PX * UI_SCALE_FAC) {")
    assert fit_at < drop_at, "the drop test must read the FITTED size, not the clamped one"

    # Spacing rides the font, so the lockup scales as one piece.
    assert "font_px * MOODBOARD_MEDIA_LABEL_GAP_RATIO" in labels
    assert "font_px * MOODBOARD_MEDIA_LABEL_INSET_RATIO" in labels


def test_a_media_name_is_placed_where_its_own_picture_is_actually_visible():
    """Moving a blocked name to the tile's top-left is not enough: a neighbour
    that covers the strip ABOVE a tile usually overlaps the top of the tile as
    well, so the name landed on that other picture regardless. The placement
    walks down a line at a time and takes the first band the tile itself shows.

    Which neighbours count depends on where the strip is, and the two cases are
    not the same: above the tile the name is in the open, so a neighbour painted
    BEFORE this tile still shows through there and must count; inside the tile
    only the neighbours painted after it can cover it."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    assert re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_PROBES (\d+)", labels)
    # One predicate serving both cases, told apart by the `inside` flag.
    assert "auto strip_is_clear = [&](const float x, const float y, const bool inside)" in labels
    assert "if (other == index || (inside && other < index)) {" in labels
    # Above the tile: every other tile is a candidate blocker.
    assert "const bool inside = !strip_is_clear(text_x, text_y, false);" in labels
    # Inside: probe downward for the first band this tile actually shows.
    assert "const float candidate = top - float(step) * line_height;" in labels
    assert "if (strip_is_clear(text_x, candidate, true)) {" in labels
    # Bounded, because this runs on every redraw.
    assert "step < MOODBOARD_MEDIA_LABEL_MAX_PROBES" in labels
    # A fully blanketed tile still gets its name, rather than losing it.
    assert "text_y = top;" in labels
    # The outline only applies to the inside case, and is turned back off.
    assert "BLF_enable(font_id, BLF_SHADOW);" in labels
    assert "BLF_disable(font_id, BLF_SHADOW);" in labels


def test_a_long_media_name_folds_in_the_middle():
    """A generated name is told apart by its tail and its extension as much as
    its head, so an over-long name keeps both ends and elides the middle. The
    offsets come from the UTF-8 helpers, never raw byte counts — a name cut
    mid-character renders as a replacement glyph."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    head = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_HEAD_CHARS (\d+)", labels).group(1)
    )
    tail = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_TAIL_CHARS (\d+)", labels).group(1)
    )
    limit = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_CHARS (\d+)", labels).group(1)
    )
    assert limit == 20
    # The ellipsis has to buy something: the fold must be shorter than the name
    # it replaces, or a 21-character name comes out longer than the original.
    assert head + tail + 3 <= limit + 2
    assert '"%s...%s"' in labels
    assert "BLI_str_utf8_offset_from_index" in labels
    assert "BLI_strlen_utf8_ex" in labels


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
