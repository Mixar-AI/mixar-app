# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent_ui spec §11: ui.sequence (validation, stop-at-first-failure,
partial results on interrupt), ui.open_menu (idname validation, popup items),
ui.run_operator (label mismatch → undo, modal confirm, redo-panel settings)
and ui.snap view/frame key mapping — all without Blender."""

import sys
import types
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.agent_ui import constants as C  # noqa: E402
from mixar.modules.agent_ui import driver as drv  # noqa: E402
from mixar.modules.agent_ui import sequence as S  # noqa: E402
from mixar.modules.agent_ui import service as svc  # noqa: E402
from mixar.modules.agent_ui import vision as V  # noqa: E402
from mixar.modules.agent_ui.errors import UIControlError  # noqa: E402
from mixar.modules.agent_ui.pump import Pump  # noqa: E402
from mixar.modules.agent_ui.service import AgentUIService  # noqa: E402

from agent_ui_fakes import FakeArea, FakeRegion, FakeWindow, FakeWM, widget  # noqa: E402


def run(gen):
    try:
        while True:
            delay = next(gen)
            assert delay >= 0
    except StopIteration as stop:
        return stop.value


def view3d_layout(props=()):
    """One window with a VIEW_3D area whose WINDOW region has a sidebar
    floating over its right edge; returns (wm, win, area, win_region, widgets)."""
    win_region = FakeRegion(201, "WINDOW", 0, 0, 1000, 800)
    ui_region = FakeRegion(202, "UI", 800, 0, 200, 800)
    area = FakeArea(21, "VIEW_3D", 0, 0, 1000, 800, regions=[win_region, ui_region])
    area.spaces = types.SimpleNamespace(active=types.SimpleNamespace(
        region_3d=types.SimpleNamespace(is_perspective=True)))
    win = FakeWindow(1, [area])
    widgets = []
    wm = FakeWM([win], widgets, props=props)
    return wm, win, area, win_region, widgets


@pytest.fixture
def rig(monkeypatch):
    wm, win, area, win_region, widgets = view3d_layout()
    monkeypatch.setattr(drv, "_wm", lambda: wm)
    monkeypatch.setattr(drv, "FIND_RETRY_WINDOW_S", 0.0)
    drv.reset_runtime_state()
    return types.SimpleNamespace(wm=wm, win=win, area=area, region=win_region, widgets=widgets)


# ------------------------------------------------------------ constants

def test_protocol_surface_has_sequence_menu_operator():
    for m in (C.RPC_SEQUENCE, C.RPC_OPEN_MENU, C.RPC_RUN_OPERATOR):
        assert m in C.RPC_METHODS and m in C.ACTION_METHODS
    assert C.ERR_OPERATOR_MISMATCH == "operator_mismatch"
    assert svc.METHOD_TIMEOUTS[C.RPC_SEQUENCE] == C.SEQUENCE_TIMEOUT_S == 90.0
    assert svc.METHOD_TIMEOUTS[C.RPC_RUN_OPERATOR] == C.RUN_OPERATOR_TIMEOUT_S == 60.0
    assert C.SEQUENCE_MAX_STEPS == 60 and C.SEQUENCE_WAIT_TICKS_MAX == 20


# -------------------------------------------------------------- validation

def test_sequence_rejects_unknown_kind_and_bad_shapes():
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"dance": 1}])
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"press": {"key": "A"}, "type": "x"}])  # two keys
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        S.validate_steps([])
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"press": {}}])
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"type": "π"}])  # non-ASCII
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"click": {"bogus": 1}}])
    assert e.value.code == C.ERR_INVALID_PARAMS


def test_sequence_denies_before_any_input():
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"press": {"key": "S"}}, {"press": {"key": "Q", "ctrl": True}}])
    assert e.value.code == C.ERR_DENIED
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"click": {"op": "WM_OT_quit_blender"}}])
    assert e.value.code == C.ERR_DENIED


def test_sequence_caps_steps_and_wait_ticks():
    with pytest.raises(UIControlError) as e:
        S.validate_steps([{"wait_ticks": 1}] * 61)
    assert e.value.code == C.ERR_INVALID_PARAMS
    assert len(S.validate_steps([{"wait_ticks": 1}] * 60)) == 60
    with pytest.raises(UIControlError):
        S.validate_steps([{"wait_ticks": 21}])
    with pytest.raises(UIControlError):
        S.validate_steps([{"wait_ticks": 0}])
    plan = S.validate_steps([{"wait_ticks": "3"}, {"focus_area": "view_3d"},
                             {"press": {"key": "E", "shift": True}}])
    assert plan[0] == ("wait_ticks", 3)
    assert plan[1] == ("focus_area", "VIEW_3D")
    assert plan[2][1] == {"key": "E", "shift": True, "ctrl": False, "alt": False, "oskey": False}


# --------------------------------------------------------------- execution

def test_sequence_runs_steps_in_order_and_reports_each(rig):
    gen = S.sequence_steps({"steps": [
        {"focus_area": "VIEW_3D"}, {"press": {"key": "S"}}, {"press": {"key": "Z"}},
        {"type": "0.1"}, {"press": {"key": "RET"}}, {"wait_ticks": 2},
    ]})
    result = run(gen)
    assert result["ok"] is True and result["completed"] == 6 and result["interrupted"] is False
    assert [r["ok"] for r in result["results"]] == [True] * 6
    types_ = [e["type"] for e in rig.win.events if e.get("value") == "PRESS"]
    # S, Z, then "0.1" typed as ZERO PERIOD ONE, then RET
    assert types_ == ["S", "Z", "ZERO", "PERIOD", "ONE", "RET"]
    assert rig.win.events[0]["type"] == "MOUSEMOVE"  # focus_area moved the pointer first


def test_sequence_stops_at_first_failure_and_marks_rest_skipped(rig):
    progress = []
    gen = S.sequence_steps({"steps": [
        {"press": {"key": "TAB"}},
        {"expect_popup": {"text": "Mesh"}},   # no popup exists → fails here
        {"press": {"key": "E"}},
        {"type": "1"},
    ]}, on_progress=lambda r: progress.append(list(r)))
    result = run(gen)
    assert result["ok"] is False and result["completed"] == 1
    kinds = [(r["kind"], r["ok"], r.get("skipped", False)) for r in result["results"]]
    assert kinds == [("press", True, False), ("expect_popup", False, False),
                     ("press", False, True), ("type", False, True)]
    assert result["results"][1]["error"]["code"] == C.ERR_NO_MATCH
    # Nothing after the failure was injected.
    assert [e["type"] for e in rig.win.events if e.get("value") == "PRESS"] == ["TAB"]
    # Progress was reported after each executed step.
    assert len(progress) >= 2 and progress[-1] == result["results"]


def test_sequence_click_step_uses_widget_query(rig):
    rig.widgets.append(widget(rig.win, rig.area, rig.region, "Cube", rect=(10, 10, 60, 30),
                              popup=True, op="MESH_OT_primitive_cube_add"))
    result = run(S.sequence_steps({"steps": [
        {"expect_popup": {"text": "Cube"}}, {"click": {"popup": True, "text": "Cube"}}]}))
    assert result["ok"] and result["completed"] == 2
    presses = [e for e in rig.win.events if e.get("type") == "LEFTMOUSE" and e.get("value") == "PRESS"]
    assert len(presses) == 1 and 10 <= presses[0]["x"] <= 60


def test_service_carries_partial_results_when_a_sequence_is_interrupted(monkeypatch, rig):
    wm = rig.wm
    for name in (C.WM_PROP_INPUT_ENABLED, C.WM_PROP_ACTION_ACTIVE, C.WM_PROP_INTERRUPT):
        wm.bl_rna.properties.add(name)
        setattr(wm, name, False)
    timers = []
    clock = {"t": 100.0}
    pump = Pump(register_timer=lambda cb, first_interval=0.0: timers.append(cb),
                now=lambda: clock["t"])
    service = AgentUIService(pump=pump, session_active=lambda: True,
                             register_timer=lambda cb, first_interval=0.0: timers.append(cb))
    monkeypatch.setattr(service, "_stop_turn", lambda sid: None)
    replies = []
    service.handle(C.RPC_SEQUENCE, {"protocol_version": 1, "steps": [
        {"press": {"key": "S"}}, {"wait_ticks": 20}, {"press": {"key": "RET"}}]}, replies.append)
    assert pump.busy and pump._active["deadline"] == 100.0 + C.SEQUENCE_TIMEOUT_S
    cb = next(t for t in timers if getattr(t, "__self__", None) is pump)
    # Step 0 (press S) completes; the user presses Esc during the wait.
    for _ in range(4):
        assert cb() is not None
    setattr(wm, C.WM_PROP_INTERRUPT, True)
    assert cb() is None
    reply = replies[-1]
    assert reply["success"] is False and reply["error"]["code"] == C.ERR_INTERRUPTED
    assert reply["interrupted"] is True and reply["completed"] == 1
    assert reply["results"][0] == {"step": 0, "kind": "press", "ok": True}


# ---------------------------------------------------------------- open_menu

def test_open_menu_validates_idname_and_registration(monkeypatch, rig):
    with pytest.raises(UIControlError) as e:
        run(S.open_menu_steps({"menu": "not a menu"}))
    assert e.value.code == C.ERR_INVALID_PARAMS
    with pytest.raises(UIControlError) as e:
        run(S.open_menu_steps({"menu": "VIEW3D_MT_edit_mesh_faces; import os"}))
    assert e.value.code == C.ERR_INVALID_PARAMS
    monkeypatch.setattr(S.bpy, "types", types.SimpleNamespace())  # nothing registered
    with pytest.raises(UIControlError) as e:
        run(S.open_menu_steps({"menu": "VIEW3D_MT_edit_mesh_faces"}))
    assert e.value.code == C.ERR_NO_MATCH


def test_open_menu_calls_menu_under_viewport_override_and_lists_items(monkeypatch, rig):
    calls = []
    monkeypatch.setattr(S.bpy, "types", types.SimpleNamespace(VIEW3D_MT_edit_mesh_faces=object()))
    monkeypatch.setattr(S.bpy, "ops", types.SimpleNamespace(
        wm=types.SimpleNamespace(call_menu=lambda name: calls.append(name))))

    class _Override:
        def __init__(self, **kw):
            calls.append(("override", sorted(kw)))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            # The menu is open now: expose its widgets.
            rig.widgets.append(widget(rig.win, rig.area, rig.region, "Face", type="Label",
                                      popup=True))
            rig.widgets.append(widget(rig.win, rig.area, rig.region, "Inset Faces|I",
                                      type="But", op="MESH_OT_inset", popup=True))
            rig.widgets.append(widget(rig.win, rig.area, rig.region, "More/Less",
                                      type="Pulldown", popup=True))
            return False
    monkeypatch.setattr(S.bpy, "context", types.SimpleNamespace(temp_override=_Override))
    result = run(S.open_menu_steps({"menu": "VIEW3D_MT_edit_mesh_faces"}))
    assert calls[0] == ("override", ["area", "region", "window"])
    assert calls[1] == "VIEW3D_MT_edit_mesh_faces"
    assert result["menu"] == "VIEW3D_MT_edit_mesh_faces"
    by_text = {i["text"]: i for i in result["items"]}
    assert by_text["Inset Faces"] == {"text": "Inset Faces", "hotkey": "I", "op": "MESH_OT_inset",
                                      "submenu": False, "type": "But"}
    assert by_text["More/Less"]["submenu"] is True
    assert by_text["Face"]["submenu"] is False


# ------------------------------------------------------------- run_operator

def _search_rig(monkeypatch, rig, redo_label, modal=False, redo_fields=()):
    """Fake wm.search_operator: typing + RET runs an operator whose F9 popup
    shows ``redo_label`` and ``redo_fields``."""
    state = {"search_open": False, "popup": [], "modal": [], "undo": 0}

    def _open_search():
        state["search_open"] = True

    class _Override:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(S.bpy, "context", types.SimpleNamespace(temp_override=_Override))
    monkeypatch.setattr(S.bpy, "ops", types.SimpleNamespace(
        wm=types.SimpleNamespace(search_operator=lambda *a, **k: _open_search())))

    def fake_find(widgets=None, **q):
        hits = []
        if state["search_open"] and q.get("popup"):
            w = widget(rig.win, rig.area, rig.region, "", type="SearchMenu", popup=True)
            hits.append(w)
        if q.get("popup") and state["popup"]:
            hits.extend(state["popup"])
        if q.get("but_type"):
            hits = [h for h in hits if h["type"] == q["but_type"]]
        if q.get("prop"):
            hits = [h for h in hits if h.get("prop") == q["prop"]]
        return hits
    monkeypatch.setattr(S.drv, "find", fake_find)

    def fake_press(win, key, shift=False, ctrl=False, alt=False, oskey=False):
        rig.win.events.append({"type": key, "ctrl": ctrl})
        if key == "RET" and state["search_open"]:
            state["search_open"] = False
            if modal:
                state["modal"] = ["MESH_OT_inset"]
        elif key == "RET" and state["modal"]:
            state["modal"] = []
        elif key == "F9" and not state["search_open"]:
            if not redo_label:  # operator without a redo panel: F9 opens nothing
                state["popup"] = []
                return
            fields = [widget(rig.win, rig.area, rig.region, redo_label, type="Label", popup=True)]
            for prop, wtype, text in redo_fields:
                fields.append(widget(rig.win, rig.area, rig.region, text, type=wtype,
                                     prop=prop, prop_owner="WinMan", popup=True))
            state["popup"] = fields
        elif key == "ESC":
            state["popup"] = []
        elif key == "Z" and ctrl:
            state["undo"] += 1
    monkeypatch.setattr(S.drv, "press", fake_press)
    monkeypatch.setattr(S, "_modal_operators", lambda: list(state["modal"]))
    return state


def test_run_operator_mismatch_undoes_and_reports(monkeypatch, rig):
    state = _search_rig(monkeypatch, rig, redo_label="Poke Faces")
    with pytest.raises(UIControlError) as e:
        run(S.run_operator_steps({"label": "Inset Faces"}))
    assert e.value.code == C.ERR_OPERATOR_MISMATCH
    assert "Poke Faces" in e.value.message and state["undo"] == 1
    keys = [e["type"] for e in rig.win.events]
    assert keys.index("F9") < keys.index("ESC") < keys.index("Z")


def test_run_operator_confirms_modal_then_sets_fields(monkeypatch, rig):
    typed = []
    state = _search_rig(monkeypatch, rig, redo_label="Inset Faces", modal=True,
                        redo_fields=[("thickness", "Num", "0.1 m"), ("use_even_offset", "Checkbox", "")])
    edit = {"target": None}

    def fake_type_text(win, text):
        typed.append(text)
        if edit["target"] is not None:  # typing into a double-clicked field
            edit["target"]["text"] = text + " m"
    monkeypatch.setattr(S.drv, "type_text", fake_type_text)
    dbl = []

    def fake_click_xy_steps(win, x, y, double=False, **mods):
        dbl.append(double)
        edit["target"] = next((w for w in state["popup"] if w.get("type") == "Num"), None)
        yield 0.01
    monkeypatch.setattr(S.drv, "click_xy_steps", fake_click_xy_steps)
    clicked = []

    def fake_click_steps(w, double=False):
        clicked.append(w.get("prop"))
        w["sel"] = not w.get("sel")
        yield 0.01
        return w
    monkeypatch.setattr(S.drv, "click_steps", fake_click_steps)

    result = run(S.run_operator_steps({"label": "inset faces", "settings": [
        {"prop": "thickness", "value": "0.2"}, {"prop": "use_even_offset", "value": True},
        {"prop": "nope", "value": "1"}]}))
    assert typed[0] == "inset faces"                       # typed into the search box
    keys = [e["type"] for e in rig.win.events]
    assert keys.count("RET") == 3                          # search + modal confirm + field
    assert result["modal_confirmed"] is True and result["modal"] == ["MESH_OT_inset"]
    assert result["operator"] == "Inset Faces" and result["redo_panel"] is True
    assert dbl == [True]                                   # number field: DOUBLE-click
    assert typed[1] == "0.2"
    assert clicked == ["use_even_offset"]
    assert [a["prop"] for a in result["applied"]] == ["thickness", "use_even_offset"]
    assert result["applied"][0]["text_after"] == "0.2 m"
    assert result["failed"] == [{"prop": "nope", "reason": "no popup widget with that prop"}]
    assert {f["prop"] for f in result["redo_fields"]} == {"thickness", "use_even_offset"}
    assert keys[-1] == "ESC" and result["popup_closed"] is True


def test_run_operator_without_redo_panel(monkeypatch, rig):
    _search_rig(monkeypatch, rig, redo_label="")  # F9 opens nothing
    monkeypatch.setattr(S.drv, "type_text", lambda win, text: None)
    result = run(S.run_operator_steps({"label": "Select All"}))
    assert result == {"operator": "Select All", "applied": [], "failed": [], "redo_fields": [],
                      "redo_panel": False, "popup_closed": True,
                      "modal_confirmed": False, "modal": []}


def test_run_operator_validates_params():
    with pytest.raises(UIControlError):
        run(S.run_operator_steps({"label": ""}))
    with pytest.raises(UIControlError):
        run(S.run_operator_steps({"label": "Bevel", "settings": "segments=3"}))
    with pytest.raises(UIControlError):
        run(S.run_operator_steps({"label": "Bevel", "settings": [{"value": "3"}]}))
    assert S._validate_settings([{"prop": "a", "value": 3}, {"prop": "b", "value": False}]) == [
        {"prop": "a", "value": "3"}, {"prop": "b", "value": "false"}]


# ------------------------------------------------------------------- snap

def test_snap_view_and_frame_key_mapping():
    assert V.view_keys("front", "none") == [("NUMPAD_1", False)]
    assert V.view_keys("back", "none") == [("NUMPAD_1", True)]
    assert V.view_keys("left", "selected") == [("NUMPAD_PERIOD", False), ("NUMPAD_3", True)]
    assert V.view_keys("top", "all") == [("HOME", False), ("NUMPAD_7", False)]
    assert V.view_keys("bottom", None) == [("NUMPAD_7", True)]
    assert V.view_keys("persp", "none", is_perspective=True) == []
    assert V.view_keys("persp", "none", is_perspective=False) == [("NUMPAD_5", False)]
    assert V.view_keys(None, "none") == []
    with pytest.raises(UIControlError):
        V.view_keys("isometric", "none")
    with pytest.raises(UIControlError):
        V.view_keys("front", "object")


def test_snap_presses_view_keys_in_the_viewport_before_capture(monkeypatch, rig):
    pressed = []
    monkeypatch.setattr(V.drv, "press", lambda win, key, **m: pressed.append((key, m.get("ctrl", False))))
    monkeypatch.setattr(V, "_is_perspective", lambda: False)
    monkeypatch.setattr(V.bpy, "context", types.SimpleNamespace(
        preferences=types.SimpleNamespace(view=types.SimpleNamespace(smooth_view=200))))
    gen = V._view_steps("persp", "selected")
    run(gen)
    assert pressed == [("NUMPAD_PERIOD", False), ("NUMPAD_5", False)]
    assert V.bpy.context.preferences.view.smooth_view == 200  # restored
    assert rig.win.events and rig.win.events[0]["type"] == "MOUSEMOVE"  # focused first


def test_service_gates_snap_view_on_enablement(monkeypatch, rig):
    timers = []
    pump = Pump(register_timer=lambda cb, first_interval=0.0: timers.append(cb), now=lambda: 0.0)
    service = AgentUIService(pump=pump, session_active=lambda: True,
                             register_timer=lambda cb, first_interval=0.0: timers.append(cb))
    calls = []
    monkeypatch.setattr(service, "ensure_enabled", lambda: calls.append("enabled"))
    monkeypatch.setattr("mixar.modules.agent_ui.vision.snap_steps",
                        lambda p: (yield 0.01))
    replies = []
    service.handle(C.RPC_SNAP, {"protocol_version": 1, "area": "VIEW_3D"}, replies.append)
    assert calls == []                                  # plain snap stays a read
    service.handle(C.RPC_SNAP, {"protocol_version": 1, "view": "front"}, replies.append)
    assert calls == ["enabled"]
    service.handle(C.RPC_SNAP, {"protocol_version": 1, "frame": "selected"}, replies.append)
    assert calls == ["enabled", "enabled"]
    service.handle(C.RPC_SNAP, {"protocol_version": 1, "frame": "none"}, replies.append)
    assert calls == ["enabled", "enabled"]


def test_service_dispatches_sequence_menu_operator(monkeypatch):
    calls = []

    def gen(p, on_progress=None):
        calls.append(("seq", p))
        yield 0.01
        return {"completed": 0, "results": [], "interrupted": False, "ok": True}
    monkeypatch.setattr("mixar.modules.agent_ui.sequence.sequence_steps", gen)
    monkeypatch.setattr("mixar.modules.agent_ui.sequence.open_menu_steps",
                        lambda p: calls.append(("menu", p)) or iter(()))
    monkeypatch.setattr("mixar.modules.agent_ui.sequence.run_operator_steps",
                        lambda p: calls.append(("op", p)) or iter(()))
    timers = []
    pump = Pump(register_timer=lambda cb, first_interval=0.0: timers.append(cb), now=lambda: 5.0)
    service = AgentUIService(pump=pump, session_active=lambda: True,
                             register_timer=lambda cb, first_interval=0.0: timers.append(cb))
    monkeypatch.setattr(service, "ensure_enabled", lambda: None)
    replies = []
    service.handle(C.RPC_SEQUENCE, {"protocol_version": 1, "steps": [{"wait_ticks": 1}]},
                   replies.append)
    assert pump.busy and pump._active["label"] == C.RPC_SEQUENCE
    assert pump._active["deadline"] == 5.0 + C.SEQUENCE_TIMEOUT_S
    cb = next(t for t in timers if getattr(t, "__self__", None) is pump)
    while cb() is not None:
        pass
    assert replies[-1]["success"] and replies[-1]["completed"] == 0
    assert calls[0][0] == "seq"
