# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour's callout box and shortcut panel (pure layout), the Creator
Program entry of the Help menu, and the actions that open that menu."""

from __future__ import annotations

import ast
import pathlib

from mixar.modules.onboarding.core.tour import actions, actions_extra
from mixar.modules.onboarding.core.tour.overlays import callout, keys

WINDOW = (0.0, 0.0, 1600.0, 1000.0)
ROW = (40.0, 880.0, 240.0, 904.0)          # a row of an open top-left menu
TOPBAR = pathlib.Path(__file__).resolve().parents[2] / "src/scripts/startup/bl_ui/space_topbar.py"


def test_callout_beside_a_menu_row_sits_right_of_it_centred_on_it():
    r = callout.callout_rect("Creator Program", "Inference credits and a community.",
                             "Help ▸ Creator Program", ROW, WINDOW, side="right")
    assert r[0] > ROW[2]
    assert abs((r[1] + r[3]) / 2 - (ROW[1] + ROW[3]) / 2) < 1.0
    assert WINDOW[0] <= r[0] and r[2] <= WINDOW[2] and WINDOW[1] <= r[1] and r[3] <= WINDOW[3]


def test_callout_under_an_anchor_flips_above_near_the_bottom_edge():
    low = (100.0, 5.0, 160.0, 25.0)
    r = callout.callout_rect("T", "Body", "", low, WINDOW, side="below")
    assert r[1] > low[3]


def test_callout_wraps_long_copy():
    assert len(callout.wrap("word " * 40)) > 1
    assert callout.wrap("") == []


def test_shortcut_panel_stays_inside_its_bounds_and_rows_light_in_order():
    rows = (("G", "Move", 100), ("Shift+A", "Add an object", 200), ("Mod+Z", "Undo", 300))
    lay = keys.keys_layout("Handy shortcuts", rows, (1590.0, 990.0), WINDOW)
    x0, y0, x1, y1 = lay["rect"]
    assert WINDOW[0] <= x0 < x1 <= WINDOW[2] and WINDOW[1] <= y0 < y1 <= WINDOW[3]
    assert keys.row_state(100, 50) == "waiting"
    assert keys.row_state(100, 150) == "lit"
    assert keys.row_state(100, 100 + keys.KEY_LIT_MS) == "done"
    assert keys._caps("Mod+Z")[0] in ("Cmd", "Ctrl")
    assert keys._caps("Opt") in (["Option"], ["Alt"])


def test_help_menu_has_the_creator_program_entry_highlighted_by_the_tour():
    tree = ast.parse(TOPBAR.read_text())
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "TOPBAR_MT_help")
    src = ast.get_source_segment(TOPBAR.read_text(), cls)
    assert "https://www.mixar.app/creator-program" in src
    assert 'text="Creator Program"' in src
    assert "depress=highlighted" in src
    assert f'"{actions_extra.HIGHLIGHT_KEY}"' in src
    assert f'"{actions_extra.HIGHLIGHT_CREATOR}"' in src


def test_new_actions_are_registered():
    for name in ("library_source", "help_menu_open", "help_menu_close"):
        assert name in actions._ACTIONS
    assert "IMAGE" in actions.TAB_IDS and "VIDEO" in actions.TAB_IDS
    assert "MEDIA" not in actions.TAB_IDS


class _Window:
    def __init__(self, opened=True):
        self.calls = []
        self._opened = opened

    def mixar_tour_menu_open(self, menu):
        self.calls.append(("open", menu))
        return self._opened

    def mixar_tour_menu_close(self):
        self.calls.append(("close",))
        return True


class _WM(dict):
    mixar_generations_source = "AI"


def test_help_menu_open_highlights_and_close_clears(monkeypatch):
    wm, win = _WM(), _Window()
    monkeypatch.setattr(actions_extra, "_wm", lambda: wm)
    monkeypatch.setattr(actions_extra.anchors, "main_window", lambda: win)
    assert actions_extra.help_menu_open({}) is True
    assert win.calls == [("open", "TOPBAR_MT_help")]
    assert wm[actions_extra.HIGHLIGHT_KEY] == actions_extra.HIGHLIGHT_CREATOR
    assert actions_extra.help_menu_close({}) is True
    assert actions_extra.HIGHLIGHT_KEY not in wm


def test_a_menu_that_fails_to_open_leaves_no_highlight(monkeypatch):
    wm, win = _WM(), _Window(opened=False)
    monkeypatch.setattr(actions_extra, "_wm", lambda: wm)
    monkeypatch.setattr(actions_extra.anchors, "main_window", lambda: win)
    assert actions_extra.help_menu_open({}) is False
    assert actions_extra.HIGHLIGHT_KEY not in wm


def test_reset_transients_puts_the_library_back_on_the_grid(monkeypatch):
    wm = _WM()
    monkeypatch.setattr(actions_extra, "_wm", lambda: wm)
    monkeypatch.setattr(actions_extra.anchors, "main_window", lambda: None)
    assert actions_extra.library_source({"source": "LIBRARY"}) is True
    assert wm.mixar_generations_source == "LIBRARY"
    actions_extra.reset_transients()
    assert wm.mixar_generations_source == "AI"
    assert actions_extra.library_source({"source": "BOGUS"}) is False
