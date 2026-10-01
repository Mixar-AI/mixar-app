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
re-targets the dialog to the bubble's host (main) window, like the quit flow
already does in `wm_window.cc`, and restores the caller's context afterwards.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WM_FILES = ROOT / "src/source/blender/windowmanager/intern/wm_files.cc"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    return text[start : text.index("\n}\n", start)]


def test_close_file_dialog_opens_in_the_bubble_host_window():
    text = _strip_comments(WM_FILES.read_text(encoding="utf-8"))
    target = _function(text, "static wmWindow *wm_close_file_dialog_target_window(")
    assert "wm_window_contains_agent_bubble_space(win)" in target
    # Prefer the bubble's top-level parent, else any non-temp main window.
    assert "win->parent" in target
    assert "WM_window_is_temp_screen(&iter_win)" in target

    dialog = _function(text, "void wm_close_file_dialog(bContext *C, wmGenericCallback *post_action)")
    redirect = dialog.index("wm_close_file_dialog_target_window(CTX_wm_manager(C), win_ctx)")
    exists = dialog.index("popup_block_name_exists(CTX_wm_screen(C)")
    invoke = dialog.index("popup_block_invoke(")
    assert redirect < exists < invoke, "the redirect must precede the dedup check and the popup"
    assert "CTX_wm_window_set(C, win_dialog);" in dialog


def test_close_file_dialog_restores_the_callers_context():
    text = _strip_comments(WM_FILES.read_text(encoding="utf-8"))
    dialog = _function(text, "void wm_close_file_dialog(bContext *C, wmGenericCallback *post_action)")
    tail = dialog[dialog.index("popup_block_invoke(") :]
    assert "CTX_wm_window_set(C, win_ctx);" in tail
    assert "CTX_wm_area_set(C, area_ctx);" in tail
    assert "CTX_wm_region_set(C, region_ctx);" in tail
