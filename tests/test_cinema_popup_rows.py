# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for the Cinema Mode popup row kinds
(Segment / Caption / Slider / Field).

The Director popups are native block popups that cannot be refreshed, so
every one of these behaviours lives in the PAINTER; nothing here is visible
to the compiler. Each pin names the line that would silently regress into
"labels clipped mid-glyph", "the slider's range clobbered by the tag" or
"stock Blender chrome inside the new UI".
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
INTERFACE = ROOT / "src/source/blender/editors/interface"

HEADER = (VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8")
POPUP = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")
RENDER = (VIEW3D / "view3d_director_popup_render.cc").read_text(encoding="utf-8")
ROW = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
ROW_HH = (INTERFACE / "interface_mixar_cinema_row.hh").read_text(encoding="utf-8")
SEGMENT = (INTERFACE / "interface_mixar_cinema_row_segment.cc").read_text(encoding="utf-8")
VALUE = (INTERFACE / "interface_mixar_cinema_row_value.cc").read_text(encoding="utf-8")
CARD_HH = (INTERFACE / "interface_mixar_profile_card.hh").read_text(encoding="utf-8")
CARD = (INTERFACE / "interface_mixar_profile_card.cc").read_text(encoding="utf-8")
WIDGETS = (INTERFACE / "interface_widgets.cc").read_text(encoding="utf-8")
CMAKE = (INTERFACE / "CMakeLists.txt").read_text(encoding="utf-8")


def _function(text: str, signature: str) -> str:
    body = text[text.index(signature) :]
    return body[: body.index("\n}\n")]


def _color_define(name: str) -> tuple[float, ...]:
    match = re.search(rf"^#define {name} \{{([^}}]+)\}}", HEADER, re.M)
    assert match is not None, f"{name} is not defined in view3d_director_cinema.hh"
    return tuple(float(part.strip().rstrip("f")) for part in match.group(1).split(","))


def _uchar_token(name: str) -> tuple[int, ...]:
    match = re.search(rf"^const uchar {name}\[4\] = \{{([^}}]+)\}};", ROW, re.M)
    assert match is not None, f"{name} is not defined in interface_mixar_cinema_row.cc"
    return tuple(int(part.strip(), 0) for part in match.group(1).split(","))


# -------------------------------------------------------------------------
# 1. Tokens mirror the cinema header (the painter cannot include it).


def test_caption_and_slider_tokens_mirror_the_cinema_header():
    caption = _color_define("CINEMA_COL_CAPTION")
    assert _uchar_token("CAPTION") == tuple(round(c * 255) for c in caption)
    speed_on = _color_define("CINEMA_COL_SPEED_ON")
    assert _uchar_token("SLIDER_ON") == tuple(round(c * 255) for c in speed_on)
    # The tokens are DEFINED in the row TU and only declared in the kit
    # header, so the mirror has one home.
    assert "extern const uchar CAPTION[4];" in ROW_HH
    assert "extern const uchar SLIDER_ON[4];" in ROW_HH
    assert "const uchar CAPTION[4]" in ROW and "const uchar SLIDER_ON[4]" in ROW


def test_the_slider_track_is_never_the_lit_chip():
    slider = _function(VALUE, "void draw_slider(")
    assert "draw_chip(" not in slider
    assert "(is_hover && !disabled) ? HOVER : TRACK" in slider
    assert "mixar_card_fill_round(&fill, fill_rad, SLIDER_ON" in slider


# -------------------------------------------------------------------------
# 2. Segment: grouped by baseline, hovered cell sized from its label.


def test_segment_group_is_the_segment_buttons_on_one_baseline():
    assert "for (Button &other : but->block->buttons())" in SEGMENT
    baseline = _function(SEGMENT, "bool same_baseline(")
    assert "a.rect.ymin - b.rect.ymin" in baseline and "a.rect.ymax - b.rect.ymax" in baseline
    member = _function(SEGMENT, "bool is_segment(")
    assert "MixarCinemaRowKind::Segment" in member
    collect = _function(SEGMENT, "void group_collect(")
    # Ordered by x, hover read from each member's own flag, never a
    # disabled member.
    assert "group->members[index - 1]->rect.xmin > other.rect.xmin" in collect
    assert "(member->flag & UI_HOVER) != 0 && (member->flag & BUT_DISABLED) == 0" in collect


def test_hovered_segment_cell_is_as_wide_as_its_label_and_others_share_the_rest():
    cell = _function(SEGMENT, "rctf cell_rect(")
    assert "fontstyle_string_width(&fs, row_label(hot)) + 2.0f * TEXT_PAD * UI_SCALE_FAC" in cell
    assert "std::clamp(need, own, std::max(own, total - others_min))" in cell
    assert "const float rest_w = (total - hot_w) / float(group.count - 1);" in cell
    # Idle: every cell is its own hit rect.
    assert "if (group.hovered < 0 || group.count < 2) {\n    return self->rect;" in cell
    # Hit rects stay the block's; the reason is documented at the top.
    assert "can_refresh" in SEGMENT
    assert "SEGMENT_MIN_W = 28.0f" in ROW


def test_segment_cell_paints_only_itself_and_reads_active_from_the_flag():
    draw = _function(SEGMENT, "void draw_segment(")
    assert "const bool lit = (but->flag & BUT_ACTIVE_DEFAULT) != 0;" in draw
    assert "draw_label(fs, &text, row_label(but), col, UI_STYLE_TEXT_CENTER, pad_slack(), pad_slack());" in draw
    # Labels shorten with an ellipsis instead of losing glyphs.
    label = _function(ROW, "void draw_label(")
    assert "text_clip_middle_ex(&fs, clipped, okwidth, minwidth, sizeof(clipped), '\\0');" in label


def test_labels_shrink_the_pad_to_a_floor_before_ellipsising():
    """A three-up "Beauty" is a few px too wide for the TEXT_PAD inset; it
    must take the padding back (down to TEXT_PAD_MIN) and draw whole, and
    only a label that still does not fit gets the ellipsis."""
    assert "const float TEXT_PAD_MIN = 4.0f;" in ROW
    slack = _function(ROW, "float pad_slack(")
    assert "(TEXT_PAD - TEXT_PAD_MIN) * UI_SCALE_FAC" in slack
    label = _function(ROW, "void draw_label(")
    assert label.index("const float need = label_w - float(BLI_rcti_size_x(&fit));") < label.index(
        "text_clip_middle_ex(&fs, clipped, okwidth, minwidth, sizeof(clipped), '\\0');"
    )
    assert "const float left = std::min(slack_left, need * 0.5f);" in label
    assert "const float okwidth = float(std::max(BLI_rcti_size_x(&fit), 0));" in label
    # Uniform: option rows, segment cells, captions and the slider label all
    # hand back their pure-padding sides; a side ending at an icon or a
    # value gives nothing.
    assert "icon_drawn ? 0.0f : pad_slack(), pad_slack()" in ROW
    assert "UI_STYLE_TEXT_CENTER, pad_slack(), pad_slack()" in SEGMENT
    assert "CAPTION, UI_STYLE_TEXT_LEFT, icon_drawn ? 0.0f : pad_slack(), pad_slack()" in VALUE
    assert "UI_STYLE_TEXT_LEFT, pad_slack(), 0.0f" in VALUE


def test_lens_type_cells_are_a_segment_group():
    lens = _function(POPUP, "ui::Block *lens_popup_create(")
    assert "popup_segment_state(but, data.camera->type == types[index].camera_type, data.editable);" in lens
    seg = _function(POPUP, "void popup_segment_state(")
    assert "director_popup_state(but, active, enabled);" in seg
    assert "ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Segment);" in seg


# -------------------------------------------------------------------------
# 3. Caption / Slider tagging in the Director popups.


def test_section_labels_tag_caption_so_every_popup_gets_the_look():
    label = _function(POPUP, "void director_popup_section_label(")
    assert "ui::UI_mixar_cinema_row_tag(label, ui::MixarCinemaRowKind::Caption);" in label
    # The Output popup's "On Moodboard" entries are captions with their icon.
    assert "ui::UI_mixar_cinema_row_tag(entry, ui::MixarCinemaRowKind::Caption);" in RENDER
    assert "ICON_FILE_MOVIE" in RENDER


def test_director_popup_state_picks_the_kind_from_the_button_type():
    state = _function(POPUP, "void director_popup_state(")
    assert "switch (ui::UI_mixar_button_type(but)) {" in state
    assert "case ui::ButtonType::NumSlider:\n      ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Slider);" in state
    # Text and Menu fields stay stock for now.
    assert "case ui::ButtonType::Text:\n    case ui::ButtonType::Menu:\n      break;" in state
    # A Row keeps the existing rule (Option, value untouched).
    assert "case ui::ButtonType::Row:\n      ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Option);" in state
    assert "ui::MixarCinemaRowKind::Active : ui::MixarCinemaRowKind::Option" in state


def test_output_popup_resolution_slider_is_tagged_by_hand():
    render = _function(RENDER, "ui::Block *render_popup_create(")
    assert "ui::UI_mixar_cinema_row_tag(resolution, ui::MixarCinemaRowKind::Slider);" in render
    # Summary caption directly under the slider; widths untouched.
    slider_at = render.index('"render_resolution_percentage"')
    summary_at = render.index("y -= label_h;", slider_at)
    assert "director_popup_section_label(block, summary, y, width);" in render[summary_at:]
    assert "director_popup_width(arg, UI_UNIT_X * 12)" in render
    assert "ui::BLOCK_KEEP_OPEN" in render and "render_popup_close" in render


# -------------------------------------------------------------------------
# 4. The tag never clobbers a value-carrying button's range.


def test_tag_leaves_hardmin_hardmax_alone_on_value_carrying_buttons():
    carries = _function(ROW, "bool UI_mixar_cinema_row_carries_value(")
    for kind in ("Num", "NumSlider", "Scroll", "Text", "Toggle", "IconToggle", "Menu"):
        assert f"ButtonType::{kind}" in carries, kind
    tag = _function(ROW, "void UI_mixar_cinema_row_tag(")
    assert "but->hardmin" not in tag and "but->hardmax" not in tag
    # The read side honours the same rule, so a flagged NumSlider is a row.
    lookup = _function(CARD, "MixarCardElement UI_mixar_card_element_get(")
    assert "but->hardmin" not in lookup and "but->hardmax" not in lookup
    assert "but->mixar_style.card" in lookup
    kind_get = _function(ROW, "MixarCinemaRowKind UI_mixar_cinema_row_kind_get(")
    assert "case ButtonType::NumSlider:" in kind_get and "return MixarCinemaRowKind::Slider;" in kind_get
    assert "case ButtonType::Text:\n      return MixarCinemaRowKind::Field;" in kind_get


def test_slider_reads_the_value_and_soft_range_from_the_button():
    slider = _function(VALUE, "void draw_slider(")
    assert "const double value = button_value_get(but);" in slider
    assert "double(but->softmax) - double(but->softmin)" in slider
    # Value right, label left, without repeating the label drawstr prefixes.
    assert "UI_STYLE_TEXT_RIGHT" in slider and "UI_STYLE_TEXT_LEFT" in slider
    value = _function(VALUE, "std::string value_text(")
    assert "drawstr.compare(0, but->str.size(), but->str) == 0" in value


# -------------------------------------------------------------------------
# 5. Edit time: chip from the painter, text from the stock pass.


def test_widgets_overlay_falls_through_to_stock_text_while_a_row_is_edited():
    draw = WIDGETS[WIDGETS.index("void draw_button(const bContext *C, ARegion *region") :]
    assert "mixar_element == MixarCardElement::CinemaRow &&\n                                 but->editstr != nullptr" in draw
    assert "if (mixar_element != MixarCardElement::None && !mixar_row_editing) {" in draw
    fallthrough = draw[draw.index("if (mixar_row_editing) {") :]
    fallthrough = fallthrough[: fallthrough.index("\n  }\n")]
    assert "UI_mixar_cinema_row_draw(but, rect, (but->flag & UI_HOVER) != 0, false);" in fallthrough
    assert "wt->draw = nullptr;" in fallthrough and "wt->custom = nullptr;" in fallthrough
    # The painter lays only the chip for Slider / Field, nothing for the rest.
    dispatch = _function(ROW, "void UI_mixar_cinema_row_draw(")
    editing = dispatch[dispatch.index("if (but->editstr != nullptr) {") :]
    editing = editing[: editing.index("\n  }\n")]
    assert "ELEM(kind, MixarCinemaRowKind::Slider, MixarCinemaRowKind::Field)" in editing
    assert "draw_chip(row, row_radius(row));" in editing
    assert "return;" in editing


def test_field_paints_nothing_while_idle():
    field = _function(VALUE, "void draw_field(")
    for painter in ("draw_chip", "draw_hover", "draw_label", "mixar_card_", "fontstyle_"):
        assert painter not in field, painter


# -------------------------------------------------------------------------
# 6. Build wiring and size rule.


def test_new_row_tus_are_built_and_under_the_size_rule():
    for name in (
        "interface_mixar_cinema_row_segment.cc",
        "interface_mixar_cinema_row_value.cc",
        "interface_mixar_cinema_row.hh",
    ):
        assert f"  {name}\n" in CMAKE, name
    for path in (
        INTERFACE / "interface_mixar_cinema_row.cc",
        INTERFACE / "interface_mixar_cinema_row_segment.cc",
        INTERFACE / "interface_mixar_cinema_row_value.cc",
        VIEW3D / "view3d_director_popup.cc",
        VIEW3D / "view3d_director_popup_render.cc",
    ):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 500, path.name
    # The public accessor keeps `interface_intern.hh` out of space_view3d.
    assert "ButtonType UI_mixar_button_type(const Button *but);" in CARD_HH
    assert "interface_intern.hh" not in POPUP
