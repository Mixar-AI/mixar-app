# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for the in-place rename in the My Cameras card.

Each row of the card is a painted name with two invisible buttons on the
same rect: the operator button that selects the camera, and — created after
it — a no-emboss Text button bound to the name the row shows. Blender's hit
test walks a block backwards, so the Text button is asked first; a no-emboss
Text button declines everything except a label edit (Ctrl held), so plain
clicks fall through to the operator; the operator button is tagged so a
double-click or Ctrl+click on it hands off to that Text the way a UI-list
row does (the Mixar hook in `do_but_BUT`), and the stock editor opens.
Every ordering below is invisible to the compiler and only shows up as a
row that stops selecting, a rename that edits the wrong datablock, or a
double-click that fires the operator twice.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
INTERFACE = ROOT / "src/source/blender/editors/interface"

RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
CINEMA_ROW = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
SECTION = (INTERFACE / "interface_mixar_section.hh").read_text(encoding="utf-8")
CARD_HH = (INTERFACE / "interface_mixar_profile_card.hh").read_text(encoding="utf-8")
HANDLERS = (INTERFACE / "interface_handlers.cc").read_text(encoding="utf-8")
UI_C_HH = (ROOT / "src/source/blender/editors/include/UI_interface_c.hh").read_text(
    encoding="utf-8"
)

QA_RECORD = 'cinema_qa_record(region, row, "director_camera", name, index);'
OP_BUTTON = 'cinema_op_button(\n        block, "MIXAR_OT_director_set_active_shot", row, "Direct this camera");'
TEXT_FIELD_CALL = (
    'cinema_text_field(\n'
    '        block, name_ptr, "name", row, "Rename this camera: double-click or Ctrl+click");'
)
TAG_CALL = "ui::UI_mixar_button_double_click_edits_label(but);"


def _rows_loop() -> str:
    """The body of the camera rows loop, up to the empty-list caption."""
    start = RIGHT.index("for (int slot = 0; slot < visible_rows; slot++) {")
    end = RIGHT.index("if (shot_count == 0) {", start)
    return RIGHT[start:end]


def _helper() -> str:
    """The body of the reusable `cinema_text_field` helper."""
    start = RIGHT.index("ui::Button *cinema_text_field(ui::Block *block,")
    end = RIGHT.index("/** Three-way segmented row", start)
    return RIGHT[start:end]


# -------------------------------------------------------------------------
# 1. Creation order: QA record, then the operator button, then the text field.


def test_text_field_is_created_after_the_operator_button_in_the_rows_loop():
    loop = _rows_loop()
    assert loop.count(OP_BUTTON) == 1
    assert loop.count(TEXT_FIELD_CALL) == 1
    # Later buttons win overlapping hits: the Text must come LAST so it is
    # asked first and can decline plain clicks in favour of the operator.
    assert loop.index(OP_BUTTON) < loop.index(TEXT_FIELD_CALL)


def test_qa_record_stays_on_the_row_rect_before_the_operator_button():
    loop = _rows_loop()
    assert loop.count(QA_RECORD) == 1
    assert loop.index(QA_RECORD) < loop.index(OP_BUTTON)


def test_text_field_and_operator_button_share_the_row_rect():
    loop = _rows_loop()
    # Both are laid over `row`; a different rect would let one control sit
    # beside the other and break the "single click selects" promise.
    assert '"MIXAR_OT_director_set_active_shot", row,' in loop
    assert 'block, name_ptr, "name", row,' in loop


# -------------------------------------------------------------------------
# 2. The field is a no-emboss Text button bound to "name", tagged Field.


def test_helper_creates_a_text_button_under_emboss_none():
    helper = _helper()
    none_set = helper.index("ui::block_emboss_set(block, blender::ui::EmbossType::None);")
    define = helper.index("ui::uiDefButR(block,")
    emboss_restore = helper.index("ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);")
    assert none_set < define < emboss_restore
    assert "ui::ButtonType::Text," in helper[define:emboss_restore]


def test_helper_binds_the_property_it_is_given_and_the_row_passes_name():
    helper = _helper()
    # The RNA pointer and property name are the button's identity across
    # the per-redraw block rebuild (`but_equals_old` → `button_rna_equals`).
    assert re.search(r"\bptr,\s*prop_name,\s*0,\s*0,\s*0,\s*tooltip\)", helper)
    assert TEXT_FIELD_CALL in _rows_loop()


def test_helper_tags_the_button_as_a_cinema_field():
    helper = _helper()
    assert "ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Field);" in helper
    assert '#include "../interface/interface_mixar_profile_card.hh"' in RIGHT


def test_tooltip_is_a_string_literal_promising_only_live_gestures():
    # Tooltips are non-owning StringRefs: a temporary would dangle.
    match = re.search(r'cinema_text_field\(\s*block, name_ptr, "name", row, ("[^"]+")\);', RIGHT)
    assert match is not None
    # Both gestures are backed by the do_but_BUT hook below.
    assert match.group(1) == '"Rename this camera: double-click or Ctrl+click"'


# -------------------------------------------------------------------------
# 3. The row edits the name it displays.


def test_row_falls_back_to_the_shot_name_pointer_when_no_camera_name():
    loop = _rows_loop()
    fallback = loop.index("if (name[0] == '\\0') {")
    block_end = loop.index("}", fallback)
    body = loop[fallback:block_end]
    assert 'RNA_string_get(&shot_ptr, "name", name);' in body
    assert "name_ptr = &shot_ptr;" in body
    # Default is the camera object, resolved before the fallback.
    assert loop.index("PointerRNA *name_ptr = &camera_ptr;") < fallback


def test_camera_pointer_outlives_the_lookup_scope():
    loop = _rows_loop()
    # Declared at row scope so the text field can bind to it after the
    # `if (camera_prop != nullptr)` block closes.
    assert "PointerRNA camera_ptr = PointerRNA_NULL;" in loop
    assert loop.index("PointerRNA camera_ptr = PointerRNA_NULL;") < loop.index(
        "camera_ptr = RNA_property_pointer_get(&shot_ptr, camera_prop);"
    )


# -------------------------------------------------------------------------
# 4. Interface-side contract: a Text button's `hardmax` is its edit buffer.


def test_cinema_row_tag_leaves_a_text_buttons_hardmax_alone():
    """`button_string_get_maxncpy` returns `hardmax` for Text buttons and
    `textedit_begin` sizes the edit string from it; a tag that stored the
    kind there would truncate every rename to five characters."""
    start = CINEMA_ROW.index("bool UI_mixar_cinema_row_carries_value(const Button *but)")
    end = CINEMA_ROW.index("}", start)
    assert "ButtonType::Text," in CINEMA_ROW[start:end]


def test_cinema_row_kind_of_a_text_button_is_field():
    start = CINEMA_ROW.index("MixarCinemaRowKind UI_mixar_cinema_row_kind_get(const Button *but)")
    end = CINEMA_ROW.index("\n}\n", start)
    body = CINEMA_ROW[start:end]
    assert re.search(r"case ButtonType::Text:\s*return MixarCinemaRowKind::Field;", body)


# -------------------------------------------------------------------------
# 5. Double-click / Ctrl+click hand-off: the operator button's tag and the
#    handlers hook that acts on it.


def _do_but_but() -> str:
    start = HANDLERS.index("static int do_but_BUT(bContext *C, Button *but,")
    end = HANDLERS.index("\n}\n", start)
    return HANDLERS[start:end]


def test_row_operator_button_is_tagged_for_label_edit_handoff():
    loop = _rows_loop()
    assert loop.count(TAG_CALL) == 1
    # Tagged right after the operator's index is set, before the Text field.
    assert loop.index('RNA_int_set(ui::button_operator_ptr_ensure(but), "index", index);') < loop.index(
        TAG_CALL
    ) < loop.index(TEXT_FIELD_CALL)


def test_tag_is_declared_publicly_and_sets_the_drawflag_bit():
    assert "void UI_mixar_button_double_click_edits_label(Button *but);" in CARD_HH
    start = CINEMA_ROW.index("void UI_mixar_button_double_click_edits_label(Button *but)")
    body = CINEMA_ROW[start : CINEMA_ROW.index("\n}\n", start)]
    assert "UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_SET(but);" in body


def test_handoff_bit_is_a_free_drawflag_bit():
    """`flag2` and `Button::flag` are full; the bit lives in `drawflag`, above
    every bit upstream's anonymous draw-flag enum defines."""
    assert "#define UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL (1 << 30)" in SECTION
    assert "(but)->drawflag |= UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL" in SECTION
    assert "(but)->drawflag & UI_BUT_DRAW_MIXAR_DBLCLICK_EDITS_LABEL" in SECTION
    start = UI_C_HH.index("#Button::drawflag, these flags should only affect how the button is drawn")
    end = UI_C_HH.index("\n};\n", start)
    bits = [int(m) for m in re.findall(r"= 1u? << (\d+)u?,", UI_C_HH[start:end])]
    assert bits, "could not read the draw-flag enum"
    assert max(bits) < 30


def test_do_but_but_hands_double_click_and_ctrl_click_to_the_label():
    body = _do_but_but()
    marker = body.index("/* Mixar:")
    hook = body.index("UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_TEST(but)")
    plain_press = body.index("button_activate_state(C, but, BUTTON_STATE_WAIT_RELEASE);")
    # Marked for the next upstream merge, gated by the tag, and checked
    # BEFORE the plain press branch that would otherwise arm the operator.
    assert marker < hook < plain_press
    hook_body = body[hook:plain_press]
    assert "event->val == KM_DBL_CLICK" in hook_body
    assert "(event->modifier & KM_CTRL)" in hook_body
    assert "but_list_row_text_activate(" in hook_body
    assert "BUTTON_ACTIVATE_TEXT_EDITING" in hook_body
    assert "return WM_UI_HANDLER_BREAK;" in hook_body
    assert '#include "interface_mixar_section.hh"' in HANDLERS


def test_handoff_mirrors_the_list_row_gesture_set():
    """The hook accepts exactly what do_but_LISTROW accepts, so the two
    rename paths never drift apart."""
    body = _do_but_but()
    hook = body.index("UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_TEST(but)")
    hook_body = body[hook : body.index("button_activate_state(C, but, BUTTON_STATE_WAIT_RELEASE);")]
    assert "ELEM(event->type, LEFTMOUSE, EVT_PADENTER, EVT_RETKEY) && (event->val == KM_PRESS)" in hook_body
    list_row = HANDLERS[HANDLERS.index("static int do_but_LISTROW(") :]
    list_row = list_row[: list_row.index("\n}\n")]
    assert "ELEM(event->type, LEFTMOUSE, EVT_PADENTER, EVT_RETKEY) && (event->val == KM_PRESS)" in list_row
