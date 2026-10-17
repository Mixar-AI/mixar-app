# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings sheet — the designer's artboard (`common/sheet/kit`) and its
painters (`interface_mixar_sheet*.cc`). The one-action contract and the
state flow are pinned by test_byok_dialog_ui.py, whose fake layout this
reuses."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_byok_dialog_ui import (  # noqa: E402
    FakeLayout, INTERFACE_DIR, RNA_UI_API, ROOT, SCRIPTS, WM_OPERATORS, _draw,
)

from mixar.modules.byok.core import model_suggestions  # noqa: E402
from mixar.modules.byok.ui.operators import byok_dialog_ui  # noqa: E402
from mixar.modules.common.sheet import kit as byok_sheet  # noqa: E402

RNA_WM_MIXAR_POPUP = ROOT / "src" / "source" / "blender" / "makesrna" / "intern" / "rna_wm_mixar_popup.cc"
SHEET_CC = INTERFACE_DIR / "interface_mixar_sheet.cc"
SHEET_HH = INTERFACE_DIR / "interface_mixar_sheet.hh"


def _sheet_kind_items():
    rna = RNA_UI_API.read_text(encoding="utf-8")
    items = re.search(r"mixar_sheet_kind_items\[\]\s*=\s*\{(.*?)\};", rna, re.S).group(1)
    return dict((name, int(value)) for value, name in re.findall(r"\{(\d+),\s*\"([A-Z_]+)\"", items))


def _with_catalog(monkeypatch):
    monkeypatch.setattr(model_suggestions, "get_provider_items", lambda: [
        ('anthropic', "Anthropic", ""), ('openai', "OpenAI", ""),
        ('openrouter', "OpenRouter", ""), ('codex', "Codex (ChatGPT sub)", ""),
        ('local', "Local (this computer)", ""),
    ])
    monkeypatch.setattr(model_suggestions, "get_model_items", lambda provider: [
        ('claude-fable-5-1', "Claude Fable 5.1", ""),
        ('claude-sonnet-5-5', "Claude Sonnet 5.5", ""),
    ])


def test_a_long_provider_name_widens_its_pill_but_stops_short_of_the_divider():
    layout = FakeLayout([], card_api=True)
    S = byok_sheet
    # A short name keeps the plate's design margin to the divider.
    assert S.row_right(layout, "OpenAI") == S.ROW_RIGHT
    # A name that needs more keeps ROW_TEXT_X of plate on both sides…
    long_name = "Codex (ChatGPT s)"   # 17 chars at the fake's 14 dp = 238 dp, + slack
    expected = S.SIDEBAR - S.LEFT_INSET - (238 + S.TEXT_SLACK + 2 * S.ROW_TEXT_X)
    assert S.ROW_MIN_RIGHT < expected < S.ROW_RIGHT
    assert S.row_right(layout, long_name) == expected
    # …until the plate would touch the divider; then the painter ellipsises.
    assert S.row_right(layout, "X" * 80) == S.ROW_MIN_RIGHT

def test_rna_sheet_kinds_cover_every_kind_python_uses():
    """Every kind the Python sheet kit names is an RNA item, and every RNA
    value has a case in the painter's switch — a missing case would draw the
    element as a stock widget."""
    items = _sheet_kind_items()
    assert items, "no sheet kinds found — regex went stale"
    used = {
        byok_sheet.TITLE, byok_sheet.CLOSE_KIND, byok_sheet.CAPTION,
        byok_sheet.PROVIDER_ROW, byok_sheet.FOOTER_ROW, byok_sheet.CHIP,
        byok_sheet.PROMPT, byok_sheet.NOTE, byok_sheet.BODY, byok_sheet.DANGER_TEXT,
        byok_sheet.PRIMARY, byok_sheet.SECONDARY, byok_sheet.DANGER_BUTTON,
        byok_sheet.INPUT, byok_sheet.DROPDOWN,
    }
    missing = used - set(items)
    assert not missing, f"sheet kinds missing from RNA items: {missing}"
    switch = re.search(r"MixarCardElement UI_mixar_sheet_element_from_kind\(.*?\n\}",
                       SHEET_CC.read_text(encoding="utf-8"), re.S).group(0)
    for name, value in items.items():
        assert f"case {value}:" in switch, f"{name} ({value}) has no painter case"
    # The active-default flag rides on the card-button restyle.
    for kind in byok_sheet._FLAG_KIND.values():
        assert f'"{kind}"' in RNA_UI_API.read_text(encoding="utf-8")


def test_providers_are_rows_and_local_is_the_footer_button(monkeypatch):
    _with_catalog(monkeypatch)
    log = _draw('IDLE', card_api=True, byok_form_provider='anthropic',
                byok_form_model='claude-fable-5-1')
    rows = [e for e in log if e.startswith("pick:provider:")]
    assert rows == [
        "pick:provider:anthropic:Anthropic",
        "pick:provider:openai:OpenAI",
        "pick:provider:openrouter:OpenRouter",
        "pick:provider:codex:Codex (ChatGPT sub)",
        "pick:provider:local:Local model",
    ]
    # Exactly one provider row, the foot (not Local) and one model chip are lit.
    assert log.count("sheet:PROVIDER_ROW:True") == 1
    assert log.count("sheet:FOOTER_ROW:False") == 1
    assert log.count("sheet:CHIP:True") == 1
    assert f"sheet_frame:{byok_sheet.HEADER}:{byok_sheet.SIDEBAR}" in log


def test_every_supported_model_is_a_chip_and_the_key_names_it(monkeypatch):
    _with_catalog(monkeypatch)
    log = _draw('IDLE', card_api=True, byok_form_provider='anthropic',
                byok_form_model='claude-sonnet-5-5')
    mark = byok_sheet.MARK
    assert f"sheet_label:CAPTION:ALL SUPPORTED {mark}ANTHROPIC{mark} MODELS" in log
    assert "pick:model:claude-fable-5-1:Claude Fable 5.1" in log
    assert "pick:model:claude-sonnet-5-5:Claude Sonnet 5.5" in log
    assert "sheet_label:PROMPT:Enter API key for Claude Sonnet 5.5 here." in log
    assert "prop:byok_form_api_key" in log
    # Save & Activate docks inside the key field: the field runs under it.
    assert "sheet:INPUT:False" in log
    assert "sheet:PRIMARY:False" in log


def test_the_sheet_keeps_the_artboard_s_height_until_it_needs_more():
    """Both columns end on the same line: the key field sits at the foot of
    the right column and the Local Model foot hugs the card's corner."""
    S = byok_sheet
    geo = S.Geometry(n_rows=7, chips_need=S.chips_height(2) + S.GAP, bottom=S.key_block_height())
    assert geo.height == S.HEIGHT
    assert geo.left_body + S.FOOTER == geo.right
    assert geo.fixed_top + geo.area + geo.bottom == geo.right
    assert geo.area == S.HEIGHT - S.HEADER - geo.fixed_top - geo.bottom

    tall = S.Geometry(n_rows=14, chips_need=0, bottom=S.key_block_height())
    assert tall.height > S.HEIGHT
    assert tall.left_body + S.FOOTER == tall.right

    wide = S.Geometry(n_rows=7, chips_need=S.chips_height(9), bottom=S.key_block_height())
    assert wide.area >= S.chips_height(9)
    assert wide.left_body + S.FOOTER == wide.right


def test_chips_wrap_like_the_artboard_s_butted_pills():
    layout = FakeLayout([], card_api=True)
    chip = 7.0 * 20 * 2 + byok_sheet.TEXT_SLACK + 2 * byok_sheet.CHIP_PAD
    rows = byok_sheet.chip_rows(layout, [("a", "x" * 20), ("b", "y" * 20), ("c", "z" * 20)],
                                avail_dp=2 * chip + 1)
    assert [len(r) for r in rows] == [2, 1]
    assert rows[0][0][2] == chip


def test_busy_states_have_no_close_button():
    for state in ('SAVING', 'REMOVING'):
        log = _draw(state, card_api=True, byok_is_active=True)
        assert f"popup_confirm:{byok_dialog_ui.CLOSE_GLYPH}" not in log


def test_the_dialog_opens_as_a_padding_free_sheet():
    """`mixar_invoke_modal_dialog(sheet=True)` (Raj's modal dialog: centred,
    main window, island hidden) must reach a dialog creator that drops its
    title row, padding and spacer rows and flags the block, or the painted
    frame would sit 7 px inside the layout's edges."""
    ops = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
           / "byok_ops.py").read_text(encoding="utf-8")
    assert "sheet=True" in ops
    rna = RNA_WM_MIXAR_POPUP.read_text(encoding="utf-8")
    assert '"sheet"' in rna and "Mixar_operator_modal_dialog_popup(C, op, width, sheet)" in rna
    wm = WM_OPERATORS.read_text(encoding="utf-8")
    assert "data->mixar_sheet = sheet;" in wm
    assert "data->mixar_sheet ? 0 :" in wm
    assert "block_flag_enable(block, ui::BLOCK_MIXAR_SHEET)" in wm
    assert "sheet ? std::string() : WM_operatortype_name(op->type, op->ptr)" in wm
    header = SHEET_HH.read_text(encoding="utf-8")
    # The Python kit and the painter share the artboard.
    for name, value in (("row_h", byok_sheet.ROW_H), ("chip_h", byok_sheet.CHIP_H),
                        ("input_h", byok_sheet.INPUT_H), ("footer_h", byok_sheet.FOOTER),
                        ("chip_pad", byok_sheet.CHIP_PAD), ("row_text_x", byok_sheet.ROW_TEXT_X),
                        ("button_h", byok_sheet.BUTTON_H)):
        assert f"inline constexpr float {name} = {float(value)}f;" in header, name
    # Type follows Mixar's text roles (ratios of the UI body), not artboard px.
    assert "inline constexpr float label_size = 1.0f;" in header
    assert "Clash" not in SHEET_CC.read_text(encoding="utf-8")


def test_a_key_needed_locks_provider_and_model(monkeypatch):
    """The account's key is not on this computer: provider and model stay as
    saved (sidebar and chips disabled), only the key is asked for."""
    _with_catalog(monkeypatch)
    log = _draw('IDLE', card_api=True, byok_is_active=True, byok_device_key_missing=True,
                byok_current_provider='anthropic', byok_current_model='claude-fable-5-1',
                byok_form_provider='anthropic', byok_form_model='claude-fable-5-1')
    assert any("Key needed on this computer" in e and e.startswith("sheet_label:DANGER_TEXT")
               for e in log), log
    assert f"op:{byok_dialog_ui.OP_REQUEST_REMOVE}" not in log  # nothing to remove here
    assert "prop:byok_form_api_key" in log


def test_a_paused_key_offers_use_and_forget(monkeypatch):
    _with_catalog(monkeypatch)
    from mixar.modules.byok.core import credential_state
    monkeypatch.setattr(credential_state, "resume_target", lambda: ('anthropic', 'claude-fable-5-1'))
    log = _draw('IDLE', card_api=True, byok_key_resumable=True,
                byok_form_provider='anthropic', byok_form_model='claude-fable-5-1')
    assert any("Paused, Mixie is answering" in e for e in log), log
    assert f"op:{byok_dialog_ui.OP_USE_KEY}" in log
    assert f"op:{byok_dialog_ui.OP_FORGET_KEY}" in log


def test_the_sidebar_links_to_the_published_byok_guide():
    """The Guide button opens the BYOK section of the docs. The anchor id must
    match the frontend section (mixie-frontend src/pages/docsByok.ts →
    YOUR_OWN_PROVIDER_SECTION id 'your-own-provider'); a drift breaks the link."""
    assert byok_dialog_ui.BYOK_GUIDE_URL == "https://www.mixar.app/docs#your-own-provider"
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_provider_settings_ui.py").read_text(encoding="utf-8")
    sidebar = source[source.index("def draw_sidebar("):source.index("\nclass FormPlan")]
    assert '"wm.url_open"' in sidebar and "BYOK_GUIDE_URL" in sidebar
    # And it is drawn: the sidebar carries the Guide pill.
    assert any(e == "op:wm.url_open" for e in _draw('IDLE', card_api=True))


def _body(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def test_painters_fit_their_text_and_leave_the_font_as_they_found_it():
    """The dropdown's value stops short of its chevron (as stock menus keep
    off their arrows); header text is ellipsised; a row is measured in the
    face it is drawn in while lit; every draw restores the UI face's weight,
    empty text included."""
    widgets = (INTERFACE_DIR / "interface_widgets.cc").read_text(encoding="utf-8")
    dropdown = _body(widgets, "static void widget_mixar_sheet_dropdown(")
    assert "rect->xmax -= UI_mixar_sheet_dropdown_text_inset();" in dropdown
    header = SHEET_HH.read_text(encoding="utf-8")
    inset = float(re.search(r"dropdown_text_right = ([\d.]+)f;", header).group(1))
    chevron = float(re.search(r"dropdown_chevron_right = ([\d.]+)f;", header).group(1))
    half = float(re.search(r"dropdown_chevron = ([\d.]+)f;", header).group(1)) / 2
    assert inset > chevron + half

    sheet = SHEET_CC.read_text(encoding="utf-8")
    text_in = _body(sheet, "void text_in(")
    empty = text_in[text_in.index("text[0] == '\\0'"):text_in.index("return;")]
    assert "restore_weight(font_id);" in empty
    assert "restore_weight(font_id);" in _body(sheet, "void text_at(")
    controls = (INTERFACE_DIR / "interface_mixar_sheet_controls.cc").read_text(encoding="utf-8")
    assert "fit(" in _body(controls, "void draw_title(")
    assert "fit(" in _body(controls, "void draw_caption(")
    width = _body(sheet, "float UI_mixar_sheet_text_width(")
    row = width[width.index("case MixarCardElement::SheetProviderRow:"):]
    assert row.index("weight = weight_strong;") < row.index("break;")


def test_a_path_fields_browse_button_is_a_docked_sheet_pill():
    """A FILE_PATH property (the Codex sign-in file) adds Blender's browse
    button after its text field; tagging the input styles the field AND turns
    that button into a docked, icon-only secondary pill (no stock grey square)."""
    src = SHEET_CC.read_text(encoding="utf-8")
    body = src[src.index("void UI_layout_mixar_sheet_tag_last("):]
    body = body[:body.index("\n}\n")]
    assert "Button *browse = but;" in body
    assert "pill.card = MixarCardElement::SheetSecondary;" in body
    assert "pill.progress = 1.0f;" in body
