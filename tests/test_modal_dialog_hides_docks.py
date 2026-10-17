# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`WindowManager.mixar_invoke_modal_dialog`: one centred dialog in the main
window with the Agent island and pill hidden while it is open.

The island and pill are always-on-top OS windows, so a dialog in the main
window was drawn behind them; one opened at the main window's stale pointer
was clamped to the bottom of the screen. The native entry point (opt-in; AI
Provider Settings is its first user):

* is centred (`WM_POPUP_POSITION_CENTER`);
* re-targets out of an Agent Bubble window to the bubble's top-level host,
  mirroring the close-file dialog;
* holds the floating docks hidden for the lifetime of its `wmOpPopUp`, whose
  destructor releases the hold — every close path (OK, Cancel, Escape,
  click-away, a file load tearing the pop-up down) ends in a `MEM_delete`.

Holds are keyed by owner so the splash and close-file dialogs, which reach
their restore from both a button and the pop-up's free callback, can no longer
release a hold that belongs to another open dialog. The keyboard follows the
holds: the first one makes the dialog's host key while a floating dock has the
keyboard (a suppressed island is only transparent on macOS and kept it), and
the last release hands it back to that dock, so after Cancel the island
composer types again instead of the viewport taking the keys as shortcuts.
"""

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WM = ROOT / "src/source/blender/windowmanager"
WM_OPERATORS = WM / "intern/wm_operators.cc"
WM_MODAL = WM / "intern/wm_mixar_modal_dialog.cc"
WM_FILES = WM / "intern/wm_files.cc"
WM_SPLASH = WM / "intern/wm_splash_screen.cc"
WM_MIXAR_HH = WM / "WM_mixar.hh"
WM_CMAKE = WM / "CMakeLists.txt"
RNA_POPUP = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar_popup.cc"
RNA_WM_MIXAR = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"
INTERACTION = ROOT / "src/source/blender/editors/space_agent_bubble/agent_bubble_interaction.cc"
BYOK = ROOT / "src/scripts/mixar/modules/byok/ui/operators/byok_ops.py"


def _code(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


# --- the native dialog -------------------------------------------------------

def test_modal_dialog_is_centred_hosted_out_of_the_island_and_holds_docks():
    body = _code(_function(WM_OPERATORS.read_text(),
                           "wmOperatorStatus Mixar_operator_modal_dialog_popup("))
    assert "data->position = WM_POPUP_POSITION_CENTER;" in body
    assert "Mixar_modal_dialog_host_window(CTX_wm_manager(C), win_ctx)" in body
    assert "CTX_wm_window_set(C, win_dialog);" in body
    # The caller's context comes back after the pop-up is registered.
    assert body.index("popup_block_ex(") < body.index("CTX_wm_window_set(C, win_ctx);")
    assert "focus_host" not in body and "Mixar_WindowMakeKey" not in body
    assert "data->mixar_docks_held = true;" in body
    # Held while the context window is the host, so the hold can key it.
    assert body.index("CTX_wm_window_set(C, win_dialog);") < body.index(
        "Mixar_floating_docks_hold(C, data);") < body.index("CTX_wm_window_set(C, win_ctx);")
    assert "wm_operator_ui_popup_ok, wm_operator_ui_popup_cancel, data, op" in body
    # Generic: no operator is singled out.
    assert not re.search(r"byok|BYOK|MIXAR_BYOK", body)


def test_dock_hold_is_released_by_the_popup_data_destructor():
    src = WM_OPERATORS.read_text()
    struct = _code(src[src.index("struct wmOpPopUp {"):src.index("};", src.index("struct wmOpPopUp {"))])
    assert "bool mixar_docks_held = false;" in struct
    assert "~wmOpPopUp()" in struct
    assert "Mixar_floating_docks_release(this);" in struct
    # Every close path frees the data with MEM_delete (destructor runs).
    for fn in ("static void dialog_exec_cb(", "static void wm_operator_ui_popup_cancel(bContext *C, void *user_data)\n{",
               "static void wm_operator_ui_popup_ok("):
        assert "MEM_delete(data);" in _function(src, fn), fn


def test_upstream_props_dialog_keeps_mouse_positioning():
    body = _function(WM_OPERATORS.read_text(), "wmOperatorStatus WM_operator_props_dialog_popup(")
    assert ("data->position = (message) ? WM_POPUP_POSITION_CENTER : "
            "WM_POPUP_POSITION_MOUSE;") in body
    assert "Mixar_floating_docks_hold" not in body
    assert "runtime->winactive" not in WM_OPERATORS.read_text()


def test_host_window_mirrors_the_close_file_dialog():
    host = _code(_function(WM_MODAL.read_text(),
                           "wmWindow *Mixar_modal_dialog_host_window("))
    assert "!Mixar_window_has_agent_bubble(win)" in host
    assert "win->parent" in host and "win_main->parent" in host
    assert "WM_window_is_temp_screen(&iter_win)" in host
    assert "intern/wm_mixar_modal_dialog.cc" in WM_CMAKE.read_text()


# --- nest-safe holds -----------------------------------------------------------

def test_holds_are_keyed_and_idempotent():
    src = _code(WM_MODAL.read_text())
    hold = _function(src, "void Mixar_floating_docks_hold(bContext *C, const void *owner)")
    release = _function(src, "void Mixar_floating_docks_release(const void *owner)")
    assert "!dock_holders().add(owner)" in hold
    assert "Mixar_FloatingDocksSuppressForModal();" in hold
    assert "!dock_holders().remove(owner)" in release
    assert "Mixar_FloatingDocksRestoreAfterModal();" in release
    assert "WM_main_add_notifier(NC_WINDOW, nullptr);" in release
    # Linux: tracked, nothing hidden.
    assert hold.index("#if defined(__APPLE__) || defined(_WIN32)") < hold.index(
        "Mixar_FloatingDocksSuppressForModal")
    for name in ("Mixar_floating_docks_hold", "Mixar_floating_docks_release",
                 "Mixar_floating_docks_held", "Mixar_modal_dialog_host_window",
                 "Mixar_window_has_agent_bubble"):
        assert name in WM_MIXAR_HH.read_text(), name


def test_the_keyboard_follows_the_first_hold_and_the_last_release():
    src = _code(WM_MODAL.read_text())
    hold = _function(src, "void Mixar_floating_docks_hold(bContext *C, const void *owner)")
    release = _function(src, "void Mixar_floating_docks_release(const void *owner)")
    # First hold only: remember the dock that had the keyboard — asked BEFORE
    # hiding (Windows moves the foreground off a hidden window) — then key the
    # dialog's host.
    assert "dock_holders().size() == 1" in hold
    assert "key_floating_dock(wm)" in hold
    assert "Mixar_modal_dialog_host_window(wm, CTX_wm_window(C))" in hold
    assert hold.index("key_floating_dock(wm)") < hold.index(
        "Mixar_FloatingDocksSuppressForModal();") < hold.index("Mixar_WindowMakeKey(")
    assert "g_key_dock = dock;" in hold
    finder = _function(src, "static wmWindow *key_floating_dock(wmWindowManager *wm)")
    assert "Mixar_window_has_agent_bubble(&win) && Mixar_WindowIsKey(ghostwin)" in finder
    # Last release only, and only to a dock that still exists (pointer + id).
    assert release.index("Mixar_FloatingDocksRestoreAfterModal();") < release.index(
        "if (dock_holders().is_empty()) {") < release.index("take_key_dock()")
    take = _function(src, "static wmWindow *take_key_dock()")
    assert "g_key_dock = nullptr;" in take
    assert "&win == dock && win.winid == winid" in take
    for ghost in ("src/intern/ghost/intern/GHOST_SystemCocoa.mm",
                  "src/intern/ghost/intern/GHOST_SystemWin32.cc"):
        assert 'extern "C" bool Mixar_WindowIsKey(void *window_handle)' in (ROOT / ghost).read_text()


def test_every_dialog_holds_with_its_context():
    for path, call in ((WM_SPLASH, "Mixar_floating_docks_hold(C, &wm_mixar_splash_dock_owner);"),
                       (WM_FILES, "Mixar_floating_docks_hold(C, close_file_dialog_name);"),
                       (WM_OPERATORS, "Mixar_floating_docks_hold(C, data);")):
        assert call in _code(path.read_text()), path.name


def test_splash_and_close_file_go_through_keyed_holds():
    # Both release from a button AND from the pop-up free callback; raw GHOST
    # calls there decremented twice and could re-show the docks under another
    # still-open dialog.
    for path, owner in ((WM_SPLASH, "&wm_mixar_splash_dock_owner"),
                        (WM_FILES, "close_file_dialog_name")):
        code = _code(path.read_text())
        assert "Mixar_FloatingDocksSuppressForModal" not in code, path.name
        assert "Mixar_FloatingDocksRestoreAfterModal" not in code, path.name
        assert f"Mixar_floating_docks_hold(C, {owner});" in code, path.name
        assert f"Mixar_floating_docks_release({owner});" in code, path.name


def test_island_does_not_collapse_on_presses_in_a_dock_hiding_dialog():
    body = _code(_function(INTERACTION.read_text(), "bool agent_bubble_should_dismiss("))
    assert "if (Mixar_floating_docks_held()) {" in body
    assert body.index("Mixar_floating_docks_held()") < body.index("for (wmWindow &win : wm->windows)")


# --- RNA ---------------------------------------------------------------------------

def test_rna_function_mirrors_invoke_props_dialog():
    rna = RNA_POPUP.read_text()
    assert '"mixar_invoke_modal_dialog", "rna_WindowManager_mixar_invoke_modal_dialog"' in rna
    assert "FUNC_NO_SELF | FUNC_USE_CONTEXT" in rna
    assert 'RNA_def_pointer(func, "operator", "Operator"' in rna
    assert 'RNA_def_int(func, "width", 300' in rna
    assert "rna_enum_operator_return_items" in rna
    assert "static int rna_WindowManager_mixar_invoke_modal_dialog(bContext *C," in rna
    assert 'RNA_def_boolean(func,\n                  "sheet",' in rna  # the AI Provider sheet
    assert "return Mixar_operator_modal_dialog_popup(C, op, width, sheet);" in rna
    host = RNA_WM_MIXAR.read_text()
    assert "RNA_def_mixar_popup_query(brna, srna);" in host
    assert len(host.splitlines()) <= 500


# --- BYOK adopts it, with a fallback -------------------------------------------------

def _invoke():
    src = BYOK.read_text()
    for cls in ast.walk(ast.parse(src)):
        if isinstance(cls, ast.ClassDef) and cls.name == "MIXAR_BYOK_OT_open_dialog":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "invoke":
                    return ast.get_source_segment(src, fn)
    raise AssertionError("invoke")


def test_byok_uses_the_native_dialog_and_falls_back():
    body = _invoke()
    native = body.index('getattr(wm, "mixar_invoke_modal_dialog", None)')
    assert body.index("if _dialog_open") < native
    # The sheet, and a binary whose modal dialog predates `sheet`.
    assert "return modal(self, width=byok_dialog_ui.SHEET_WIDTH, sheet=True)" in body
    assert "return modal(self, width=byok_dialog_ui.SHEET_WIDTH)" in body
    # Older binaries: the previous main-window host override.
    assert native < body.index("_dialog_host_window(context)")
    assert native < body.index("wm.invoke_props_dialog(self, width=CARD_DIALOG_WIDTH)")
    # The single-instance flag is set before either path and cleared on failure.
    assert body.index("_dialog_open = True") < native
    assert body.count("_dialog_open = False") == 2
    src = BYOK.read_text()
    assert "island_dialog" not in src
    assert len(src.splitlines()) <= 500


# --- the single-instance flag on every open path (functional) ----------------

def _byok():
    """The dialog operator module under the bpy mock (test_byok_dialog_ui
    installs it) and that suite's fake WindowManager."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_byok_dialog_ui import _wm, byok_ops
    return byok_ops, _wm


def _invoke_with(monkeypatch, wm):
    """Run open_dialog.invoke against ``wm`` with its data prep stubbed."""
    byok_ops, _ = _byok()
    monkeypatch.setattr(byok_ops.byok_client, "mutation_in_flight", lambda: False)
    monkeypatch.setattr(byok_ops, "_saved_provider_model", lambda wm: (None, None))
    monkeypatch.setattr(byok_ops, "_prefill_from_prompt", lambda wm, prompt: None)
    monkeypatch.setattr(byok_ops.model_suggestions, "is_loaded", lambda: True)
    monkeypatch.setattr(byok_ops, "_dialog_host_window", lambda context: None)
    monkeypatch.setattr(byok_ops, "_dialog_open", False)
    context = SimpleNamespace(window_manager=wm, window=None)
    return byok_ops.MIXAR_BYOK_OT_open_dialog().invoke(context, None)


def test_a_failing_dialog_open_releases_the_single_instance_flag(monkeypatch):
    """Every open path that raises must clear `_dialog_open`, or the dialog
    could never be opened again this session."""
    byok_ops, _wm = _byok()

    def boom(*_args, **_kwargs):
        raise RuntimeError("no window")

    # Old binary: the plain props dialog.
    wm = _wm('IDLE', invoke_props_dialog=boom)
    with pytest.raises(RuntimeError):
        _invoke_with(monkeypatch, wm)
    assert byok_ops._dialog_open is False

    # A modal dialog predating `sheet`, whose plain retry fails too.
    calls = []

    def modal(op, width, **kwargs):
        calls.append(kwargs)
        if kwargs.get("sheet"):
            raise TypeError("modal() got an unexpected keyword argument 'sheet'")
        raise RuntimeError("no window")

    wm = _wm('IDLE', mixar_invoke_modal_dialog=modal)
    with pytest.raises(RuntimeError):
        _invoke_with(monkeypatch, wm)
    assert calls == [{"sheet": True}, {}]
    assert byok_ops._dialog_open is False

    # And a successful open keeps it set until the dialog closes.
    wm = _wm('IDLE', mixar_invoke_modal_dialog=lambda op, width, **kw: {'RUNNING_MODAL'})
    assert _invoke_with(monkeypatch, wm) == {'RUNNING_MODAL'}
    assert byok_ops._dialog_open is True
    byok_ops.MIXAR_BYOK_OT_open_dialog().cancel(SimpleNamespace(window_manager=wm))
    assert byok_ops._dialog_open is False
