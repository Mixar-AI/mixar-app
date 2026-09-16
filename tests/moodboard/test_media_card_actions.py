# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A selected reference image or movie carries Rename / Preview / Export.

A finished inference node wears an Edit / Preview / Export row just above its
card. A reference the user dropped on the board is the same kind of thing to
look at and take away, but it has no settings, so its first button is Rename.
The row is C++ canvas content; these pins are source-level, and the Python
half (export scoping, the rename operator) is checked through the source and
through the bpy-free media helper.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The row
# --------------------------------------------------------------------------- #


def test_the_media_row_is_built_and_wired_like_the_node_row():
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    node_ui = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")
    header = _read(SPACE_MIXIE / "mixie_draw_moodboard_intern.hh")
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")

    assert "mixie_draw_moodboard_media_actions.cc" in cmake
    assert "moodboard_add_selected_media_actions(" in header
    assert "moodboard_add_media_card_actions(" in header
    # Added to the SAME canvas block as the node controls, before it is ended:
    # that is what makes the buttons scale with the tile and hit-test at
    # every zoom.
    controls = node_ui.split("void mixie_draw_moodboard_graph_controls(")[1]
    assert controls.index("moodboard_add_selected_media_actions(") < controls.index(
        "UI_block_end(C, block);"
    )
    # Same geometry as the node row, from the same two constants, so a
    # reference and a card selected side by side wear their rows on one line.
    for metric in ("MOODBOARD_NODE_HEADER_LIFT", "MOODBOARD_NODE_HEADER_ROW_H"):
        assert metric in actions, metric
    assert "const int width = height;" in actions, "icon buttons must stay square"
    assert "int(media_rect.xmax) - width" in actions


def test_the_three_buttons_keep_the_node_rows_order_and_glyphs():
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    tile = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_tile_controls.cc")

    # Export claims the corner, Preview steps left of it, and the pencil takes
    # the left-most slot -- laid out right to left, so Export comes FIRST in
    # the source, exactly as on the node row.
    export = actions.index('"MIXIE_OT_moodboard_export_images"')
    preview = actions.index('"MIXIE_OT_moodboard_preview_media"')
    rename = actions.index('"MIXIE_OT_moodboard_rename_media"')
    assert export < preview < rename
    # Same glyph in the same place means the same thing on a reference and on
    # a card: the download arrow, the window, and the pencil the node row
    # uses for Edit.
    assert "ICON_IMPORT," in actions and "ICON_IMPORT," in tile
    assert "ICON_EXPORT," not in actions
    assert "ICON_WINDOW," in actions and "ICON_WINDOW" in tile
    assert "ICON_GREASEPENCIL," in actions
    # The exporter opens a file dialog; exec'ing straight through would write
    # to whatever path it last held. Rename has nothing to open (the field
    # appears in place on the next redraw), so it execs.
    export_call = actions.split('"MIXIE_OT_moodboard_export_images"')[1].split(";")[0]
    assert "OpCallContext::InvokeDefault" in export_call
    rename_call = actions.split('"MIXIE_OT_moodboard_rename_media"')[1].split(";")[0]
    assert "OpCallContext::ExecDefault" in rename_call


def test_every_button_is_scoped_to_the_tile_it_sits_on():
    """With several references selected the button on one tile must act on
    THAT tile, so each button carries the media's own graph id."""
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    assert actions.count('"media_id", media_id)') == 3
    # And never the node-result field: a reference is addressed by its own id.
    assert '"node_id", media_id)' not in actions


def test_the_row_is_only_for_selected_standalone_media():
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    body = actions.split("void moodboard_add_selected_media_actions(")[1]
    # Cheapest test first: this runs on every redraw over the whole board.
    assert body.index('RNA_boolean_get(&media, "selected")') < body.index(
        '"embedded_node_id"'
    )
    # Node-owned media is a card's result and already has the card's row.
    assert "RNA_property_string_length(&media, embedded) == 0" in body
    # The rect comes from the shared per-frame cache, keyed by the media id;
    # an id-less tile has nothing for a click to act on and gets no row.
    assert "cache->outputs.lookup_ptr(media_id)" in body
    # Culled on the ROW's own footprint: it hangs above the tile, so a tile
    # just below the viewport still has its buttons on screen.
    assert "moodboard_media_action_row_rect(*media_rect, &row_rect)" in body
    assert "moodboard_view_rect_to_region(v2d, region, row_rect, &row_region)" in body


def test_the_media_name_never_lands_under_the_buttons():
    """The name floats left-aligned on the same line the row is right-aligned
    on; on a narrow tile they would meet. The label pass reads the row's rect
    through the ONE definition the button layout uses and treats it as taken."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    header = _read(SPACE_MIXIE / "mixie_draw_moodboard_intern.hh")

    assert "void moodboard_media_action_row_rect(" in header
    assert "void moodboard_media_action_row_rect(" in actions
    assert "moodboard_media_action_row_rect(media_canvas, &row_canvas)" in labels
    assert "has_action_row" in labels
    # Only the float ABOVE the tile competes with the row; inside the tile the
    # row is above and clear, so the check is gated on `!inside`.
    clear = labels.split("auto strip_is_clear = ")[1]
    assert "!inside && tile.has_action_row" in clear
    # Only a SELECTED tile has a row, so only a selected tile reserves one.
    collect = labels.split("if (tile.selected) {")[1].split("tiles.append(tile)")[0]
    assert "moodboard_media_action_row_rect(" in collect


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #


def test_preview_opens_a_reference_by_its_own_id():
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview_window.cc")
    # A second property, not a second meaning for `node_id`: a reference is
    # addressed by its own `node_id` field and a node's result through the
    # node's `embedded_node_id`, and those are different lookups.
    # The property is defined with SKIP_SAVE: a remembered media id would
    # open a different reference than the one whose button was pressed.
    media_def = preview.split('RNA_def_string(ot->srna,\n                        "media_id"')
    assert len(media_def) == 2, "media_id must be defined as an operator property"
    assert "PROP_SKIP_SAVE" in media_def[1].split("}")[0]
    assert "static Image *preview_image_for_media(" in preview
    lookup = preview.split("static Image *preview_image_for_media(")[1].split("\n}")[0]
    assert 'mixie_rna_string_get_clamped(&item, "node_id"' in lookup
    assert '"embedded_node_id"' not in lookup
    # The reference's row sets media_id and wins; the card's row sets node_id.
    assert "media_id[0] ? preview_image_for_media(&scene_ptr, media_id)" in preview
    assert "preview_image_for_node(&scene_ptr, node_id)" in preview


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_export_button_on_a_reference_saves_that_reference():
    ops = _read(MOODBOARD / "ui/operators/export_ops.py")
    assert "def _media_to_export(scene, node_id=\"\", media_id=\"\"):" in ops
    routing = ops.split("def _media_to_export(")[1].split("\n\n\n")[0]
    # The reference id is checked first; both ids are never set together.
    assert routing.index("if media_id:") < routing.index("if node_id:")
    assert "return standalone_exportable_media(scene, media_id)" in routing
    assert "media_id: StringProperty(default=\"\", options={'SKIP_SAVE'})" in ops
    # Both entry points of the exporter pass the reference id through.
    assert ops.count("_media_to_export(scene, self.node_id, self.media_id)") == 2


def test_standalone_exportable_media_resolves_by_the_medias_own_id():
    from mixar.modules.moodboard.core import media_utils

    reference = SimpleNamespace(
        image=object(), node_id="ref-1", embedded_node_id="", selected=False
    )
    other = SimpleNamespace(
        image=object(), node_id="ref-2", embedded_node_id="", selected=True
    )
    result = SimpleNamespace(
        image=object(), node_id="res-1", embedded_node_id="ref-1", selected=False
    )
    purged = SimpleNamespace(image=None, node_id="ref-3", embedded_node_id="", selected=True)
    scene = SimpleNamespace(mixie_moodboard_images=[reference, other, result, purged])

    # The id names the reference itself, never a result that happens to be
    # owned by a node with that id, and selection plays no part.
    assert media_utils.standalone_exportable_media(scene, "ref-1") == [reference]
    assert media_utils.standalone_exportable_media(scene, "ref-2") == [other]
    # A purged datablock is nothing the exporter can write.
    assert media_utils.standalone_exportable_media(scene, "ref-3") == []
    assert media_utils.standalone_exportable_media(scene, "") == []
    assert media_utils.standalone_exportable_media(scene, None) == []
    # The node lookup is unchanged and stays the other field.
    assert media_utils.node_exportable_media(scene, "ref-1") == [result]


# --------------------------------------------------------------------------- #
# Rename
# --------------------------------------------------------------------------- #


def test_rename_is_in_place_not_a_dialog():
    """The first version opened a props dialog, which exposed the internal
    media id as a field beside the name over a stock OK/Cancel row -- a form
    for something that is one word. The pencil (and F2) now turn the name
    painted above the tile into a text field where it stands: Enter applies,
    Escape keeps the old name."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_rename_media.cc")
    actions = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_actions.cc")
    header = _read(SPACE_MIXIE / "mixie_intern.hh")
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")

    assert not (MOODBOARD / "ui/operators/media_rename_ops.py").exists()
    assert "mixie_moodboard_ops_rename_media.cc" in cmake
    assert "WM_operatortype_append(MIXIE_OT_moodboard_rename_media)" in space
    assert "void MIXIE_OT_moodboard_rename_media(wmOperatorType *ot);" in header
    assert "invoke_props_dialog" not in ops

    # The operator only marks WHICH tile is being renamed; the field does the
    # rest. Runtime state keyed on the scene session uid, never scene data.
    assert "moodboard_media_rename_begin(scene, media_id)" in ops
    assert "scene->id.session_uid" in ops
    assert "RNA_string_set" not in ops.split("moodboard_rename_media_exec")[1].split("}\n\n")[0]
    # F2 arrives with no id: exactly one selected reference is the fallback.
    assert "single_selected_media_id(&scene_ptr, media_id)" in ops
    assert "if (++found > 1)" in ops
    # SKIP_SAVE, or F2 (which sets nothing) would rename the last pencil's tile.
    media_def = ops.split('RNA_def_string(ot->srna,\n                                     "media_id"')
    assert len(media_def) == 2
    assert "PROP_SKIP_SAVE" in media_def[1].split("}")[0]
    # Starting a rename is not an edit; the field's RNA write pushes the undo.
    assert "OPTYPE_UNDO" not in ops

    # The field: bound straight to the Image datablock's name, so applying the
    # edit IS the rename and RNA uniquifies a clash; kept alive through
    # Blender's own temporary-rename mechanism.
    field = actions.split("static bool moodboard_add_media_rename_field(")[1].split("\n}")[0]
    assert "ButType::Text" in field
    assert '"name"' in field
    assert "return UI_but_active_only(C, region, block, field);" in field
    assert "MOODBOARD_MEDIA_RENAME_MIN_W" in field and "MOODBOARD_MEDIA_RENAME_MIN_W" in header
    # It stands on the row's line, in the row's place: while renaming, the
    # three buttons are not drawn, and when the edit ends the state is cleared
    # and the row comes back on the next redraw.
    loop = actions.split("void moodboard_add_selected_media_actions(")[1]
    assert "if (moodboard_media_rename_is_active(scene, media_id)) {" in loop
    renaming = loop.split("if (moodboard_media_rename_is_active(scene, media_id)) {")[1]
    assert "moodboard_media_rename_end();" in renaming.split("else {")[0]
    assert "ED_region_tag_redraw(region);" in renaming.split("else {")[0]
    assert "moodboard_add_media_card_actions(block, *media_rect, media_id);" in renaming.split(
        "else {"
    )[1]
    # The pencil execs the operator (nothing to invoke: the field appears on
    # the next redraw and focuses itself).
    pencil = actions.split('"MIXIE_OT_moodboard_rename_media"')[1].split(";")[0]
    assert "OpCallContext::ExecDefault" in pencil


def test_the_painted_name_yields_to_the_rename_field():
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")
    assert "moodboard_media_rename_is_active(scene, media_id)" in labels
    assert "if (!tile.selected || tile.renaming) {" in labels


def test_f2_renames_the_selected_reference_when_no_node_is_active():
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    invoke = ops.split("class MIXIE_OT_moodboard_rename_node")[1].split("def invoke(")[1].split(
        "def execute("
    )[0]
    assert "bpy.ops.mixie.moodboard_rename_media()" in invoke
    # Only the id-less (keymap) path falls through; the context menu's
    # node-scoped call still reports on a vanished node.
    assert "if not self.node_id:" in invoke
