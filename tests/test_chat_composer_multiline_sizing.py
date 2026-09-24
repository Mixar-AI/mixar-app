# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The composer box is sized from the metrics the multi-line painter draws with.

QA: a pasted paragraph showed 3-4 blank "line breaks" under the text that no
key could delete, and the field went black after a few Shift+Enter presses.
The footer counted wrapped lines with a 1.2x font the painter had dropped and
quantised the box to a fixed 20px row, so the painter's visible_lines never
matched the counted lines; every draw also re-tagged the region size.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/source/blender/editors/space_mixie_chat"
LAYOUT = (CHAT / "mixie_chat_footer_layout.cc").read_text(encoding="utf-8")
INTERN = (CHAT / "mixie_chat_footer_intern.hh").read_text(encoding="utf-8")
WIDGETS = (ROOT / "src/source/blender/editors/interface/interface_widgets.cc").read_text(
    encoding="utf-8"
)


def body(source, start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin + len(start))]


def test_line_count_wraps_with_the_painters_font_and_width():
    count = body(LAYOUT, "int footer_layout_get_input_line_count(", "\n}\n")
    assert "1.2f" not in count
    assert "footer_cache_get_theme()" in count
    assert "theme->side_padding" in count
    assert "FOOTER_DEFAULT_SIDE_PADDING" not in count
    assert "FOOTER_TEXT_MARGIN_X * U.widget_unit + 0.5f" in count
    assert "#define FOOTER_TEXT_MARGIN_X 0.4f" in (CHAT / "mixie_chat_footer_constants.hh").read_text()
    assert "4.0f * U.pixelsize" in count
    painter = body(WIDGETS, "static void widget_draw_text_multiline(", "static void widget_draw_textbox")
    assert "uiFontStyle chat_fstyle = *fstyle;" in painter
    assert "1.2f" not in painter


def test_box_height_holds_exactly_the_counted_rows():
    helper = body(LAYOUT, "int footer_layout_input_row_base(", "\n}\n")
    assert 'BLF_height(fstyle.uifont_id, "Wg", 2) + 2.0f * U.pixelsize' in helper
    assert "4.0f * U.pixelsize" in helper
    assert "std::ceil(scaled / scale)" in helper
    painter = body(WIDGETS, "static void widget_draw_text_multiline(", "static void widget_draw_textbox")
    assert 'BLF_height(fontid, "Wg", 2) + 2.0f * U.pixelsize' in painter
    assert "const int top_inset = padded_input ? 0 : int(4.0f * U.pixelsize);" in painter
    input_style = (ROOT / "src/source/blender/editors/interface/mixar/style.cc").read_text()
    assert 'STREQ(RNA_property_identifier(button.rnaprop), "mixie_chat_input")' in input_style
    height = body(LAYOUT, "int footer_layout_calculate_height(", "\n}\n")
    positions = body(LAYOUT, "void footer_layout_calculate_positions(", "\n}\n")
    assert "footer_layout_input_row_base(input_line_count)" in height
    assert "footer_layout_input_row_base(input_line_count)" in positions
    assert "FOOTER_UI_UNIT_BASE * effective_lines" not in LAYOUT
    assert "int footer_layout_input_row_base(int input_line_count);" in INTERN
    assert "FOOTER_INPUT_MAX_LINE_COUNT (6)" in INTERN




def test_multiline_painter_restores_the_blocks_alpha_blend():
    painter = body(WIDGETS, "static void widget_draw_text_multiline(", "static void widget_draw_textbox")
    tail = painter[painter.rindex("GPU_blend(GPU_BLEND_NONE);"):]
    assert "GPU_blend(GPU_BLEND_ALPHA);" in tail
