# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo is held while an agent works in any scene tab (parallel scenes)."""

from types import SimpleNamespace

from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.ui.operators import undo_ops


def _rig(monkeypatch, states, runs=()):
    scenes = [SimpleNamespace(name=n, mixie_session_id="s-" + n) for n in states]
    session = SimpleNamespace(get_state=lambda sc: states[sc.name], run_open=lambda sc: sc.name in runs)
    monkeypatch.setattr(undo_ops, "get_session_manager", lambda: session)
    import mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops as tabs
    monkeypatch.setattr(tabs, "real_scenes", lambda: scenes)
    monkeypatch.setattr(undo_ops, "slog", lambda *a, **kw: None)


def _event(**kw):
    base = {"type": "Z", "value": "PRESS", "ctrl": False, "oskey": False, "shift": False, "alt": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_only_a_working_tab_counts(monkeypatch):
    _rig(monkeypatch, {"A": SessionState.IDLE, "B": SessionState.BUSY, "C": SessionState.IDLE}, runs={"C"})
    assert undo_ops.working_tabs() == ["B", "C"]
    _rig(monkeypatch, {"A": SessionState.IDLE})
    assert undo_ops.working_tabs() == []


def test_the_undo_chords_and_nothing_else():
    assert undo_ops.is_undo_chord(_event(ctrl=True))
    assert undo_ops.is_undo_chord(_event(oskey=True, shift=True))
    assert not undo_ops.is_undo_chord(_event())                       # plain Z
    assert not undo_ops.is_undo_chord(_event(ctrl=True, alt=True))    # Alt chord
    assert not undo_ops.is_undo_chord(_event(ctrl=True, value="RELEASE"))
    assert not undo_ops.is_undo_chord(_event(type="Y", ctrl=True))


def test_refusal_names_the_tabs_and_the_action(monkeypatch):
    monkeypatch.setattr(undo_ops, "slog", lambda *a, **kw: None)
    reports = []
    undo_ops.refuse(False, lambda kind, text: reports.append((kind, text)), ["B", "C"])
    undo_ops.refuse(True, lambda kind, text: reports.append((kind, text)), ["B"])
    assert reports[0][0] == {"WARNING"} and "B, C" in reports[0][1] and reports[0][1].startswith("Undo")
    assert reports[1][1].startswith("Redo")


# -- Edit menu: the same hold for the mouse ----------------------------------


class _Layout:
    def __init__(self):
        self.calls = []
        self.enabled = True

    def _rec(self, kind, *a, **kw):
        self.calls.append((kind, a, kw))
        return SimpleNamespace(name="", keep_open=True)

    def column(self):
        col = _Layout()
        self.calls.append(("column", col))
        return col

    def operator(self, *a, **kw): return self._rec("operator", *a, **kw)
    def label(self, *a, **kw): return self._rec("label", *a, **kw)
    def separator(self, *a, **kw): return self._rec("separator", *a, **kw)
    def prop(self, *a, **kw): return self._rec("prop", *a, **kw)
    def menu(self, *a, **kw): return self._rec("menu", *a, **kw)


def _ctx():
    return SimpleNamespace(preferences=SimpleNamespace(view=SimpleNamespace(show_developer_ui=False)),
                           tool_settings=SimpleNamespace(lock_object_mode=False))


def _ops(layout):
    out = []
    for c in layout.calls:
        if c[0] == "operator":
            out.append(c[1][0])
        elif c[0] == "column":
            out.extend(_ops(c[1]))
    return out


def test_edit_menu_shows_the_hold_instead_of_undo_entries_while_a_tab_works(monkeypatch):
    _rig(monkeypatch, {"Kitchen": SessionState.BUSY, "Scene": SessionState.IDLE})
    stock = []
    monkeypatch.setattr(undo_ops, "_stock_edit_draw", lambda self, ctx: stock.append(1))
    menu = SimpleNamespace(layout=_Layout())
    undo_ops.draw_edit_menu(menu, _ctx())
    assert stock == []
    ops = _ops(menu.layout)
    assert "ed.undo" not in ops and "ed.redo" not in ops
    assert not any(c[0] == "menu" for c in menu.layout.calls)          # no Undo History submenu
    held = [c[1] for c in menu.layout.calls if c[0] == "column"][0]
    assert held.enabled is False
    labels = [c[1][0] if c[1] else c[2].get("text") for c in held.calls if c[0] == "label"]
    assert any("Undo is unavailable while an agent works in Kitchen" in (l or "") for l in labels)
    assert "screen.userpref_show" in ops                                # the rest of the menu stays


def test_edit_menu_is_the_stock_menu_while_no_tab_works(monkeypatch):
    _rig(monkeypatch, {"Scene": SessionState.IDLE})
    stock = []
    monkeypatch.setattr(undo_ops, "_stock_edit_draw", lambda self, ctx: stock.append(1))
    menu = SimpleNamespace(layout=_Layout())
    undo_ops.draw_edit_menu(menu, _ctx())
    assert stock == [1] and menu.layout.calls == []


def test_install_and_uninstall_swap_the_draw_once(monkeypatch):
    stock_draw = lambda self, ctx: None
    menu = SimpleNamespace(draw=stock_draw)
    monkeypatch.setattr(undo_ops.bpy.types, "TOPBAR_MT_edit", menu, raising=False)
    monkeypatch.setattr(undo_ops, "_stock_edit_draw", None)
    undo_ops.install_edit_menu_hold()
    assert menu.draw is undo_ops.draw_edit_menu and undo_ops._stock_edit_draw is stock_draw
    undo_ops.install_edit_menu_hold()                                   # idempotent
    assert undo_ops._stock_edit_draw is stock_draw
    undo_ops.uninstall_edit_menu_hold()
    assert menu.draw is stock_draw and undo_ops._stock_edit_draw is None
