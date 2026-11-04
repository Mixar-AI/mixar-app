# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared sheet kit (`modules/common/sheet/kit.py`, used by AI Provider
settings and Connect MCP): the snippet, switch, status dot and foot
glyph primitives, their stock-widget fallback, and the C++ side they rely
on (RNA kinds, painter cases, shared tokens)."""

import re
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.common.sheet import kit as S

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "src" / "source" / "blender" / "editors" / "interface"
SHEET_HH = INTERFACE / "interface_mixar_sheet.hh"
SHEET_CC = INTERFACE / "interface_mixar_sheet.cc"
RNA_UI_API = ROOT / "src" / "source" / "blender" / "makesrna" / "intern" / "rna_ui_api.cc"
SHEET_API = ('mixar_sheet', 'mixar_sheet_label', 'mixar_sheet_text_width', 'mixar_card_button')


class Layout:
    def __init__(self, log, api):
        self.log, self.api = log, api
        self.enabled, self.alignment = True, 'EXPAND'
        self.scale_y = self.ui_units_x = self.ui_units_y = 0.0

    def _sub(self, *_a, **_kw):
        sub = Layout(self.log, self.api)
        self.log.append(("layout", sub))
        return sub

    row = column = box = _sub

    def separator(self, factor=1.0):
        pass

    def label(self, text="", icon='NONE', translate=True):
        self.log.append(("label", text, icon))

    def operator(self, idname, text="", icon='NONE', translate=True, emboss=True):
        props = SimpleNamespace()
        self.log.append(("op", idname, text, icon, props))
        return props

    def __getattr__(self, name):
        if name in SHEET_API and self.__dict__["api"]:
            return getattr(self, "_" + name)
        raise AttributeError(name)

    def _mixar_sheet(self, kind, lit=False, extra=0.0):
        self.log.append(("tag", kind, lit, extra, self))

    def _mixar_sheet_label(self, text="", kind='BODY', lit=False, extra=0.0, translate=True):
        self.log.append(("sheet_label", kind, text, lit, extra))

    def _mixar_sheet_text_width(self, kind, text):
        return 5.0 * len(text)

    def _mixar_card_button(self, kind='CARD', active_default=False):
        self.log.append(("flag", kind, active_default))


def _run(api, primitive, *args, **kwargs):
    log = []
    result = primitive(Layout(log, api), *args, **kwargs)
    return log, result


def _sheet_calls(log):
    return [entry for entry in log if entry[0] in ("tag", "sheet_label", "flag")]


def test_every_new_primitive_degrades_to_stock_widgets_without_the_painters():
    lines = ["{", '  "mcpServers": {}', "}"]
    for primitive, args, kwargs in (
        (S.snippet, (lines,), dict(dock=("mixar.copy_mcp_setup", "Copy"))),
        (S.snippet, (lines,), {}),
        (S.switch, ("mixar.set_mcp_ui_control", "Let AI apps control", True), {}),
        (S.status_dot, (S.STATUS_DANGER,), {}),
        (S.choice, ("mixar.mcp_pick_app", "Other app", S.FOOTER_ROW, False),
         dict(extra=S.FOOT_TERMINAL, app="OTHER")),
    ):
        log, _ = _run(False, primitive, *args, **kwargs)
        assert not _sheet_calls(log), (primitive.__name__, log)
        assert any(entry[0] in ("label", "op") for entry in log), primitive.__name__
    # The fallback snippet is a box of plain labels, every line kept.
    log, copy = _run(False, S.snippet, lines, dock=("mixar.copy_mcp_setup", "Copy"))
    assert [entry[1] for entry in log if entry[0] == "label"] == lines and copy is not None
    # The fallback switch is the checkbox it stands for.
    log, _ = _run(False, S.switch, "mixar.set_mcp_ui_control", "Let", True)
    assert [entry[3] for entry in log if entry[0] == "op"] == ["CHECKBOX_HLT"]


def test_with_the_painters_each_primitive_is_tagged_with_its_kind():
    log, copy = _run(True, S.snippet, ["a", "b"], dock=("mixar.copy_mcp_setup", "Copy"))
    [snippet] = [entry for entry in log if entry[0] == "sheet_label"]
    assert snippet[1] == S.SNIPPET and snippet[2] == "a\nb" and snippet[4] == S.snippet_dock_width(
        Layout([], True), "Copy")
    [tag] = [entry for entry in log if entry[0] == "tag"]
    assert tag[1:4] == (S.SECONDARY, False, S.DOCK_CORNER)
    # The corner pill keeps its own height: its row is scaled relative to the block's.
    pill_row = [entry[1] for entry in log if entry[0] == "layout"][-1]
    assert abs(pill_row.scale_y * S.snippet_height(2) - (S.DOCK_INSET + S.BUTTON_H)) < 1e-6
    assert tag[4].ui_units_x == S.units(snippet[4])   # the docked column is pinned to its width
    assert copy is not None and ("flag", "CARD", False) in log

    log, _ = _run(True, S.switch, "mixar.set_mcp_ui_control", "Let", True)
    assert [entry[1:3] for entry in log if entry[0] == "tag"] == [(S.SWITCH, True)]

    for state, lit, extra in ((S.STATUS_ON, True, 0.0), (S.STATUS_DANGER, False, 1.0),
                              (S.STATUS_DIM, False, 0.0)):
        log, _ = _run(True, S.status_dot, state)
        assert [entry[1:] for entry in log if entry[0] == "sheet_label"] == [
            (S.STATUS_DOT_KIND, "", lit, extra)]

    log, _ = _run(True, S.choice, "mixar.mcp_pick_app", "Other app", S.FOOTER_ROW, True,
                  extra=S.FOOT_TERMINAL, app="OTHER", model="")
    [op] = [entry for entry in log if entry[0] == "op"]
    assert vars(op[4]) == {"app": "OTHER"}  # empty choices are left unset
    assert [entry[1:4] for entry in log if entry[0] == "tag"] == [(S.FOOTER_ROW, True, 1.0)]


def test_code_wraps_at_the_measured_columns_and_keeps_every_character():
    text = '{\n  "command": "' + "/very/long/path" * 12 + '"\n}'
    lines = S.wrap_code(text, 40)
    assert all(len(line) <= 40 for line in lines)
    assert "".join("".join(lines).split()) == "".join(text.split())
    # Measured: 10 dp per character (the fake's 5 half-px), one column of headroom.
    assert S.snippet_columns(Layout([], True), 405) == 39
    assert S.snippet_columns(Layout([], False), 400) == S.SNIPPET_COLUMNS
    assert S.snippet_height(1) == S.INPUT_H
    assert S.snippet_height(10) == 2 * S.SNIPPET_PAD_Y + 10 * S.SNIPPET_LINE_H


def test_rna_kinds_and_painter_cases_cover_the_new_primitives():
    rna = RNA_UI_API.read_text(encoding="utf-8")
    items = re.search(r"mixar_sheet_kind_items\[\]\s*=\s*\{(.*?)\};", rna, re.S).group(1)
    kinds = dict((name, int(value)) for value, name in re.findall(r"\{(\d+),\s*\"([A-Z_]+)\"", items))
    assert {S.SNIPPET: 16, S.SWITCH: 17, S.STATUS_DOT_KIND: 18}.items() <= kinds.items()
    sheet = SHEET_CC.read_text(encoding="utf-8")
    for element, value in (("SheetSnippet", 16), ("SheetSwitch", 17), ("SheetStatusDot", 18)):
        assert f"case {value}:\n      return MixarCardElement::{element};" in sheet
        assert f"case MixarCardElement::{element}:" in sheet[sheet.index("bool UI_mixar_sheet_draw_element("):]
    assert "element <= MixarCardElement::SheetStatusDot" in sheet
    types = (ROOT / "src" / "source" / "blender" / "editors" / "include" / "UI_mixar_types.hh").read_text()
    order = types[types.index("SheetDropdown,"):types.index("Count,")]
    assert order.index("SheetSnippet,") < order.index("SheetSwitch,") < order.index("SheetStatusDot,")
    cmake = (INTERFACE / "CMakeLists.txt").read_text()
    assert "interface_mixar_sheet_blocks.cc" in cmake


def test_the_kit_and_the_painters_share_the_new_tokens():
    header = SHEET_HH.read_text(encoding="utf-8")
    for name, value in (("snippet_line_h", S.SNIPPET_LINE_H), ("snippet_pad_x", S.SNIPPET_PAD_X),
                        ("snippet_pad_y", S.SNIPPET_PAD_Y), ("switch_w", S.SWITCH_W),
                        ("switch_gap", S.SWITCH_GAP), ("status_dot", S.STATUS_DOT),
                        ("dock_corner", S.DOCK_CORNER), ("footer_terminal", S.FOOT_TERMINAL)):
        assert f"inline constexpr float {name} = {float(value)}f;" in header, name
    blocks = (INTERFACE / "interface_mixar_sheet_blocks.cc").read_text(encoding="utf-8")
    assert "fit(font_id, line.c_str()" in blocks  # a snippet line never runs past its box


def test_the_kit_is_shared_and_registers_nothing():
    """Not under a ui/ folder (auto-discovery would import it as UI)."""
    path = Path(S.__file__)
    assert "ui" not in path.relative_to(ROOT / "src" / "scripts").parts
    assert not hasattr(S, "classes") and not hasattr(S, "register")
    assert not (ROOT / "src/scripts/mixar/modules/byok/ui/operators/byok_sheet.py").exists()
