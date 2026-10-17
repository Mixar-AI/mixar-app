# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The "Save changes before closing?" dialog must never open inside an Agent
Bubble window.

Cmd+N (and Cmd+O / quit) with the island focused fires the Window keymap in
the bubble window, so the operator's context window IS the island and the
dialog was created there. The dialog suppresses every floating dock (alpha 0,
mouse ignored) while it is open, so it hid itself together with the island:
the user saw the island vanish and could never answer the prompt. The overlay
re-targets the dialog to the bubble's host (main) window through the shared
`Mixar_modal_dialog_host_window` (wm_mixar_modal_dialog.cc) and restores the
caller's context afterwards. The keyboard is the dock hold's job: on macOS the
suppressed island is only transparent and kept the keyboard, so Esc / Return /
typing never reached the dialog. The first `Mixar_floating_docks_hold` makes
the host key while a dock has the keyboard and the last release hands it back
(pinned in tests/test_modal_dialog_hides_docks.py); the dialog holds while its
host is the context window.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WM_FILES = ROOT / "src/source/blender/windowmanager/intern/wm_files.cc"
WM_MODAL = ROOT / "src/source/blender/windowmanager/intern/wm_mixar_modal_dialog.cc"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    return text[start : text.index("\n}\n", start)]


def test_close_file_dialog_opens_in_the_bubble_host_window():
    text = _strip_comments(WM_FILES.read_text(encoding="utf-8"))
    # One host-window rule for every dock-hiding dialog: no local copy.
    assert "wm_close_file_dialog_target_window" not in text
    host = _function(_strip_comments(WM_MODAL.read_text(encoding="utf-8")),
                     "wmWindow *Mixar_modal_dialog_host_window(")
    # Prefer the bubble's top-level parent, else any non-temp main window.
    assert "win->parent" in host
    assert "WM_window_is_temp_screen(&iter_win)" in host

    dialog = _function(text, "void wm_close_file_dialog(bContext *C, wmGenericCallback *post_action)")
    redirect = dialog.index("Mixar_modal_dialog_host_window(CTX_wm_manager(C), win_ctx)")
    exists = dialog.index("popup_block_name_exists(CTX_wm_screen(C)")
    invoke = dialog.index("popup_block_invoke(")
    assert redirect < exists < invoke, "the redirect must precede the dedup check and the popup"
    assert "CTX_wm_window_set(C, win_dialog);" in dialog


def test_close_file_dialog_holds_the_docks_from_its_host_window():
    text = _strip_comments(WM_FILES.read_text(encoding="utf-8"))
    dialog = _function(text, "void wm_close_file_dialog(bContext *C, wmGenericCallback *post_action)")
    # The hold reads the host from the context window, so it follows the
    # redirect; the keyboard moves there with the hold, not per dialog.
    assert dialog.index("CTX_wm_window_set(C, win_dialog);") < dialog.index(
        "wm_mixar_floating_docks_suppress_for_modal(C);") < dialog.index("popup_block_invoke(")
    assert "Mixar_floating_docks_hold(C, close_file_dialog_name);" in text
    assert "Mixar_WindowMakeKey" not in text
    assert "focus_host" not in text


def test_one_bubble_window_check_and_host_rule_for_quit_and_file_dialogs():
    wm_window = _strip_comments((WM_FILES.parent / "wm_window.cc").read_text(encoding="utf-8"))
    for text in (_strip_comments(WM_FILES.read_text(encoding="utf-8")), wm_window):
        assert "wm_window_contains_agent_bubble_space" not in text
        assert "Mixar_window_has_agent_bubble(" in text
    assert "wm_quit_target_window" not in wm_window
    quit_fn = _function(wm_window, "void wm_quit_with_optional_confirmation_prompt(bContext *C, wmWindow *win)")
    assert "win = Mixar_modal_dialog_host_window(wm, win);" in quit_fn


def test_close_file_dialog_restores_the_callers_context():
    text = _strip_comments(WM_FILES.read_text(encoding="utf-8"))
    dialog = _function(text, "void wm_close_file_dialog(bContext *C, wmGenericCallback *post_action)")
    tail = dialog[dialog.index("popup_block_invoke(") :]
    assert "CTX_wm_window_set(C, win_ctx);" in tail
    assert "CTX_wm_area_set(C, area_ctx);" in tail
    assert "CTX_wm_region_set(C, region_ctx);" in tail
