# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent_ui geometry targets / click / select (spec §10) — projection
offset math, ordering and filters, the wire record shape, off-screen and
occluded refusals, and select_geometry failure accounting — all without
Blender (bpy is the conftest MagicMock; helpers are monkeypatched)."""

import sys
import types
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.agent_ui import constants as C  # noqa: E402
from mixar.modules.agent_ui import driver as drv  # noqa: E402
from mixar.modules.agent_ui import geometry as G  # noqa: E402
from mixar.modules.agent_ui import service as svc  # noqa: E402
from mixar.modules.agent_ui.errors import UIControlError  # noqa: E402
from mixar.modules.agent_ui.pump import Pump  # noqa: E402
from mixar.modules.agent_ui.service import AgentUIService  # noqa: E402

from agent_ui_fakes import FakeArea, FakeRegion, FakeWindow, FakeWM  # noqa: E402


def run(gen):
    try:
        while True:
            delay = next(gen)
            assert delay >= 0
    except StopIteration as stop:
        return stop.value


def rec(index, center, normal=(0, 0, 1), area=1.0, length=None, selected=False,
        window_xy=None, visible=None, faces=()):
    return {"index": index, "world_center": tuple(center), "normal": tuple(normal),
            "area": area, "length": length, "selected": selected,
            "window_xy": window_xy, "visible": visible, "faces": tuple(faces)}


# ---------------------------------------------------------------- constants

def test_protocol_surface_has_geometry_methods():
    assert C.RPC_GEOMETRY_TARGETS in C.RPC_METHODS
    assert C.RPC_CLICK_GEOMETRY in C.ACTION_METHODS
    assert C.RPC_SELECT_GEOMETRY in C.ACTION_METHODS
    assert C.RPC_GEOMETRY_TARGETS not in C.ACTION_METHODS  # a read
    assert C.ERR_OCCLUDED == "occluded"
    assert svc.METHOD_TIMEOUTS[C.RPC_SELECT_GEOMETRY] == C.SELECT_GEOMETRY_TIMEOUT_S == 60.0


# --------------------------------------------------------------- projection

def test_project_adds_region_offset_and_rejects_offscreen(monkeypatch):
    region = FakeRegion(1, "WINDOW", x=400, y=50, width=1000, height=800)

    class V3D:
        @staticmethod
        def location_3d_to_region_2d(reg, rv3d, co, default=None):
            return None if co == "behind" else co
    monkeypatch.setattr(G, "_view3d_utils", lambda: V3D)
    assert G.project(region, None, (10.4, 20.6)) == (410, 71)
    assert G.project(region, None, "behind") is None
    assert G.project(region, None, (1000.0, 10.0)) is None   # x == width -> outside
    assert G.project(region, None, (-1.0, 10.0)) is None
    assert G.region_to_window(region, 0, 0) == (400, 50)


def test_poly_area_world_is_exact_for_planar_polygons():
    square = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]
    assert abs(G._poly_area_world(square) - 4.0) < 1e-9
    tilted = [(0, 0, 0), (0, 3, 0), (0, 3, 4), (0, 0, 4)]
    assert abs(G._poly_area_world(tilted) - 12.0) < 1e-9
    assert G._poly_area_world([(0, 0, 0), (1, 0, 0)]) == 0.0


# ------------------------------------------------------------- sort/filter

def test_order_targets_all_sorts():
    rs = [rec(0, (0, 0, 1), area=4.0), rec(1, (2, -1, 0), area=1.0), rec(2, (-1, 3, -2), area=9.0)]
    assert [r["index"] for r in G.order_targets(rs, "index")] == [0, 1, 2]
    assert [r["index"] for r in G.order_targets(rs, "area")] == [2, 0, 1]      # largest first
    assert [r["index"] for r in G.order_targets(rs, "z")] == [2, 1, 0]
    assert [r["index"] for r in G.order_targets(rs, "-z")] == [0, 1, 2]
    assert [r["index"] for r in G.order_targets(rs, "-x")] == [1, 0, 2]
    assert [r["index"] for r in G.order_targets(rs, "y")] == [1, 0, 2]
    assert [r["index"] for r in G.order_targets(rs, "distance", (2, -1, 0))] == [1, 0, 2]
    with pytest.raises(UIControlError) as exc:
        G.order_targets(rs, "bogus")
    assert exc.value.code == C.ERR_INVALID_PARAMS
    # edges sort by length under "area"
    es = [rec(0, (0, 0, 0), area=None, length=1.0), rec(1, (0, 0, 0), area=None, length=5.0)]
    assert [r["index"] for r in G.order_targets(es, "area")] == [1, 0]


def test_filter_targets_visible_and_selected():
    rs = [rec(0, (0, 0, 0), visible=True, selected=False),
          rec(1, (0, 0, 0), visible=False, selected=True),
          rec(2, (0, 0, 0), visible=None, selected=True),
          rec(3, (0, 0, 0), visible=True, selected=True)]
    assert [r["index"] for r in G.filter_targets(rs, visible_only=True)] == [0, 3]
    assert [r["index"] for r in G.filter_targets(rs, selected_only=True)] == [1, 2, 3]
    assert [r["index"] for r in G.filter_targets(rs, True, True)] == [3]


def test_target_record_shape():
    out = G.target_record(rec(5, (0.123456, 0, 1), normal=(0, 0, 1), area=4.0,
                              selected=False, window_xy=(812.0, 640.0), visible=True))
    assert out == {"index": 5, "window_xy": [812, 640], "world_center": [0.1235, 0.0, 1.0],
                   "normal": [0.0, 0.0, 1.0], "area": 4.0, "length": None,
                   "visible": True, "selected": False}
    off = G.target_record(rec(6, (0, 0, 0), area=None, length=2.0, window_xy=None, visible=False))
    assert off["window_xy"] is None and off["visible"] is False and off["length"] == 2.0


# ------------------------------------------------------------ geometry_targets

class FakeObj:
    def __init__(self, name="Cube", otype="MESH", mode="OBJECT"):
        self.name, self.type, self.mode = name, otype, mode
        self.dimensions = (2.0, 2.0, 2.0)


@pytest.fixture
def scene3d(monkeypatch):
    """A window with a VIEW_3D area (region offset 100,40) + geometry helpers
    stubbed: 3 faces, one off-screen, one occluded."""
    win_region = FakeRegion(201, "WINDOW", 100, 40, 1000, 800)
    view = FakeArea(21, "VIEW_3D", 100, 40, 1000, 800, regions=[win_region])
    win = FakeWindow(2, [view])
    wm = FakeWM([win], [], props=())
    monkeypatch.setattr(drv, "_wm", lambda: wm)
    drv.reset_runtime_state()
    obj = FakeObj()
    objects = MagicMock()
    objects.get = lambda name: obj if name == "Cube" else None
    monkeypatch.setattr(G.bpy, "data", types.SimpleNamespace(objects=objects))
    monkeypatch.setattr(G, "view3d_region", lambda: (win, view, win_region, "rv3d"))
    monkeypatch.setattr(G, "_mode", lambda: "EDIT_MESH")
    monkeypatch.setattr(G, "_edit_object_name", lambda: "Cube")
    monkeypatch.setattr(G, "_select_mode", lambda: (False, False, True))
    monkeypatch.setattr(G, "_view_origin", lambda region, rv3d: (0.0, -5.0, 0.0))
    records = [rec(0, (0, 0, 1), normal=(0, 0, 1), area=4.0),
               rec(1, (0, 0, -1), normal=(0, 0, -1), area=4.0),
               rec(2, (9, 9, 9), normal=(1, 0, 0), area=1.0)]
    monkeypatch.setattr(G, "element_records", lambda o, e: [dict(r) for r in records])
    proj = {0: (600, 500), 1: (600, 300), 2: None}
    vis = {0: True, 1: False, 2: False}

    def annotate(recs, region, rv3d, o, element, want_visible=True):
        for r in recs:
            r["window_xy"] = proj[r["index"]]
            r["visible"] = vis[r["index"]]
        return recs
    monkeypatch.setattr(G, "_annotate", annotate)
    flags = {0: False, 1: False, 2: False}

    def select_flag(o, element, index):
        if index not in flags:
            raise UIControlError(C.ERR_NO_MATCH, "out of range")
        return flags[index]
    monkeypatch.setattr(G, "select_flag", select_flag)
    monkeypatch.setattr(G, "_count_selected", lambda o, e: sum(flags.values()))

    def on_click(x, y, shift=False):
        # a shift-click toggles the element under the pointer
        for idx, xy in proj.items():
            if xy == (x, y):
                flags[idx] = (not flags[idx]) if shift else True
    return types.SimpleNamespace(win=win, region=win_region, obj=obj, flags=flags,
                                 proj=proj, vis=vis, on_click=on_click)


def test_geometry_targets_result(scene3d):
    out = G.geometry_targets({"object": "Cube", "element": "face", "sort": "-z", "limit": 999})
    assert out["object"] == "Cube" and out["element"] == "FACE" and out["mode"] == "EDIT_MESH"
    assert out["view"]["region_rect"] == [100, 40, 1100, 840]
    assert out["total"] == 3 and out["returned"] == 3
    assert [t["index"] for t in out["targets"]] == [2, 0, 1]
    only_visible = G.geometry_targets({"object": "Cube", "element": "FACE", "visible_only": True})
    assert only_visible["total"] == 1 and only_visible["targets"][0]["index"] == 0
    assert only_visible["targets"][0]["window_xy"] == [600, 500]
    with pytest.raises(UIControlError) as exc:
        G.geometry_targets({"object": "Nope", "element": "FACE"})
    assert exc.value.code == C.ERR_NO_MATCH
    with pytest.raises(UIControlError) as exc:
        G.geometry_targets({"object": "Cube", "element": "BLOB"})
    assert exc.value.code == C.ERR_INVALID_PARAMS


# -------------------------------------------------------------- click_geometry

def _hook_clicks(monkeypatch, scene3d):
    real = drv.click_xy_steps

    def click_xy_steps(win, x, y, double=False, shift=False, ctrl=False, alt=False):
        scene3d.on_click(int(x), int(y), shift=shift)
        return real(win, x, y, double=double, shift=shift, ctrl=ctrl, alt=alt)
    monkeypatch.setattr(drv, "click_xy_steps", click_xy_steps)


def test_click_geometry_offscreen_and_occluded_refuse_before_any_click(monkeypatch, scene3d):
    _hook_clicks(monkeypatch, scene3d)
    with pytest.raises(UIControlError) as exc:
        run(G.click_geometry_steps({"object": "Cube", "element": "FACE", "index": 2}))
    assert exc.value.code == C.ERR_NO_MATCH
    with pytest.raises(UIControlError) as exc:
        run(G.click_geometry_steps({"object": "Cube", "element": "FACE", "index": 1}))
    assert exc.value.code == C.ERR_OCCLUDED
    assert not [e for e in scene3d.win.events if e.get("type") == "LEFTMOUSE"]


def test_click_geometry_clicks_projected_point_with_shift_for_extend(monkeypatch, scene3d):
    _hook_clicks(monkeypatch, scene3d)
    out = run(G.click_geometry_steps({"object": "Cube", "element": "FACE", "index": 0,
                                      "extend": True}))
    assert out == {"index": 0, "window_xy": [600, 500], "selected": True, "mode": "EDIT_MESH"}
    presses = [e for e in scene3d.win.events if e.get("type") == "LEFTMOUSE"]
    assert presses and all(e["shift"] is True for e in presses)
    assert (presses[0]["x"], presses[0]["y"]) == (600, 500)
    # deselect: toggles with shift until the flag reads False
    out = run(G.click_geometry_steps({"object": "Cube", "element": "FACE", "index": 0,
                                      "deselect": True}))
    assert out["selected"] is False


def test_click_geometry_enters_edit_mode_and_select_mode_via_keys(monkeypatch, scene3d):
    _hook_clicks(monkeypatch, scene3d)
    state = {"mode": "OBJECT", "sel": (True, False, False)}
    monkeypatch.setattr(G, "_mode", lambda: state["mode"])
    monkeypatch.setattr(G, "_select_mode", lambda: state["sel"])
    monkeypatch.setattr(G, "_select_object", lambda obj: None)
    real_press = drv.press

    def press(win, key, **mods):
        if key == "TAB":
            state["mode"] = "EDIT_MESH"
        if key == "THREE":
            state["sel"] = (False, False, True)
        real_press(win, key, **mods)
    monkeypatch.setattr(drv, "press", press)
    out = run(G.click_geometry_steps({"object": "Cube", "element": "FACE", "index": 0}))
    keys = [e["type"] for e in scene3d.win.events if e.get("value") == "PRESS"]
    assert keys.index("TAB") < keys.index("THREE") < keys.index("LEFTMOUSE")
    assert out["mode"] == "EDIT_MESH" and out["selected"] is True


# ------------------------------------------------------------- select_geometry

def test_select_geometry_accounts_for_failures(monkeypatch, scene3d):
    _hook_clicks(monkeypatch, scene3d)
    out = run(G.select_geometry_steps({"object": "Cube", "element": "FACE",
                                       "indices": [0, 1, 2, 7], "mode": "replace"}))
    assert out["requested"] == [0, 1, 2, 7]
    assert out["selected"] == [0]
    assert {f["index"]: f["reason"] for f in out["failed"]} == {
        1: C.ERR_OCCLUDED, 2: C.ERR_NO_MATCH, 7: C.ERR_NO_MATCH}
    assert out["count_selected_total"] == 1
    # replace mode deselected all first (Alt+A) before any click
    presses = [e for e in scene3d.win.events if e.get("value") == "PRESS"]
    alt_a = next(i for i, e in enumerate(presses) if e["type"] == "A" and e.get("alt"))
    first_click = next(i for i, e in enumerate(presses) if e["type"] == "LEFTMOUSE")
    assert alt_a < first_click
    assert all(e["shift"] for e in presses if e["type"] == "LEFTMOUSE")


def test_select_geometry_extend_skips_already_selected(monkeypatch, scene3d):
    _hook_clicks(monkeypatch, scene3d)
    scene3d.flags[0] = True
    out = run(G.select_geometry_steps({"object": "Cube", "element": "FACE",
                                       "indices": [0], "mode": "extend"}))
    assert out["selected"] == [0] and out["failed"] == []
    assert not [e for e in scene3d.win.events if e.get("type") == "LEFTMOUSE"]
    with pytest.raises(UIControlError) as exc:
        run(G.select_geometry_steps({"object": "Cube", "element": "FACE",
                                     "indices": list(range(C.SELECT_GEOMETRY_MAX + 1))}))
    assert exc.value.code == C.ERR_INVALID_PARAMS


# ------------------------------------------------------------------ service

def test_service_dispatches_geometry_methods(monkeypatch):
    calls = []
    monkeypatch.setattr(G, "geometry_targets", lambda p: calls.append(("targets", p)) or {"total": 0})

    def gen(p):
        calls.append(("select", p))
        yield 0.01
        return {"requested": []}
    monkeypatch.setattr(G, "select_geometry_steps", gen)
    timers = []
    pump = Pump(register_timer=lambda cb, first_interval=0.0: timers.append(cb), now=lambda: 100.0)
    service = AgentUIService(pump=pump, session_active=lambda: True,
                             register_timer=lambda cb, first_interval=0.0: timers.append(cb))
    monkeypatch.setattr(service, "ensure_enabled", lambda: None)
    replies = []
    service.handle(C.RPC_GEOMETRY_TARGETS, {"protocol_version": 1, "object": "Cube",
                                            "element": "FACE"}, replies.append)
    assert replies[-1] == {"success": True, "total": 0} and calls[0][0] == "targets"
    service.handle(C.RPC_SELECT_GEOMETRY, {"protocol_version": 1, "object": "Cube",
                                           "element": "FACE", "indices": [1]}, replies.append)
    assert pump.busy and pump._active["deadline"] == 100.0 + C.SELECT_GEOMETRY_TIMEOUT_S
    assert pump._active["label"] == C.RPC_SELECT_GEOMETRY
