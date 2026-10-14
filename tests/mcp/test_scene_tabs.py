# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP clients make and switch scene tabs like the drawer, at most once per call,
and the connector follows them so every later tool targets that tab."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from mixar.modules.common.ui_control.constants import MAX_SCENES, UIError
from mixar.modules.common.ui_control.core import schema, service
from mixar.modules.common.ui_control.core.receipts import Receipts
from mixar.modules.mcp_bridge.core import connector, scene_tabs


class Tab(SimpleNamespace):
    def __hash__(self):
        return id(self)


@pytest.fixture
def tabs(monkeypatch):
    pool = Tab(name="Pool", mixie_session_id="sess-pool")
    made, switched = [], []
    state = SimpleNamespace(tabs=[pool], shown=pool, made=made, switched=switched)

    def new_scene_tab(name=""):
        scene = Tab(name=name or "Scene", mixie_session_id="")
        state.tabs.append(scene)
        state.shown = scene
        made.append(scene)
        return scene

    def switch_scene_tab(scene, was=None):
        switched.append(scene)
        state.shown = scene
        return True

    ops = SimpleNamespace(real_scenes=lambda: list(state.tabs), ordered_tabs=lambda: list(state.tabs),
                          new_scene_tab=new_scene_tab, switch_scene_tab=switch_scene_tab)
    monkeypatch.setattr(scene_tabs, "_ops", lambda: ops)
    monkeypatch.setattr(scene_tabs, "_shown", lambda: state.shown)
    monkeypatch.setattr(scene_tabs, "_gate", lambda: None)
    monkeypatch.setattr(scene_tabs, "_session", lambda: SimpleNamespace(
        get_state=lambda scene: SimpleNamespace(value="idle")))
    from mixar.modules.space_mixie_chat.core import scene_identity
    monkeypatch.setattr(scene_identity, "adopt_scene", lambda scene: False)
    return state


def test_scene_tools_are_local_free_and_validated():
    tools = {tool["name"]: tool for tool in schema.tools()}
    assert {"mixar_scenes", "mixar_scene_new", "mixar_scene_switch"} <= set(tools)
    assert tools["mixar_scene_new"]["_meta"]["mixar/domain"] == "scenes"
    assert tools["mixar_scenes"]["annotations"]["readOnlyHint"] is True
    assert tools["mixar_scene_new"]["annotations"]["readOnlyHint"] is False
    schema.validate("mixar_scene_new", {"name": "Classroom | Morning Light"})
    for bad in ({"name": "a\nb"}, {"name": ""}, {"show": False}):
        with pytest.raises(UIError):
            schema.validate("mixar_scene_new", bad)


def test_new_tab_is_made_by_the_drawer_path_and_gets_a_session(tabs):
    result = scene_tabs.new_scene("Classroom")
    assert [scene.name for scene in tabs.made] == ["Classroom"]
    assert result["name"] == "Classroom" and result["shown"] is True
    assert result["session"] and result["session"] == tabs.made[0].mixie_session_id
    listed = scene_tabs.list_scenes()["scenes"]
    assert [(entry["name"], entry["shown"]) for entry in listed] == [("Pool", False), ("Classroom", True)]


def test_switch_needs_one_matching_tab(tabs):
    assert scene_tabs.switch_scene("sess-pool")["name"] == "Pool"
    with pytest.raises(UIError, match="mixar_scenes"):
        scene_tabs.switch_scene("sess-missing")


def test_tab_limit_refuses_before_anything_is_made(tabs):
    tabs.tabs.extend(Tab(name=f"T{i}", mixie_session_id=f"s{i}") for i in range(MAX_SCENES))
    with pytest.raises(UIError, match="scene tabs"):
        scene_tabs.preflight("mixar_scene_new", {})
    assert tabs.made == []


def test_a_retried_create_never_makes_a_second_tab(tabs, tmp_path, monkeypatch):
    receipts = Receipts(tmp_path / "receipts.sqlite")
    monkeypatch.setattr(service, "_receipts", receipts)
    monkeypatch.setattr(service, "_signed_in", lambda: None)
    monkeypatch.setattr(service.observe, "invalidate", lambda: None)
    call = str(uuid4())
    request = SimpleNamespace(name="mixar_scene_new", args={"name": "Classroom"}, call_id=call,
                              session="", claimed=False)
    first = service._scene_tool(request)
    receipts.finish(call, "succeeded")
    again = service._scene_tool(SimpleNamespace(**{**vars(request), "claimed": False}))
    assert first["name"] == "Classroom" and len(tabs.made) == 1
    assert again["replayed"] is True and again["status"] == "succeeded"
    receipts.close()


def test_a_refused_create_leaves_no_uncertain_receipt(tabs, tmp_path, monkeypatch):
    receipts = Receipts(tmp_path / "receipts.sqlite")
    monkeypatch.setattr(service, "_receipts", receipts)
    monkeypatch.setattr(service, "_signed_in", lambda: None)
    tabs.tabs.extend(Tab(name=f"T{i}", mixie_session_id=f"s{i}") for i in range(MAX_SCENES))
    call = str(uuid4())
    request = SimpleNamespace(name="mixar_scene_new", args={}, call_id=call, session="", claimed=False)
    with pytest.raises(UIError):
        service._scene_tool(request)
    assert request.claimed is False and receipts.status(call)["status"] == "unavailable"
    receipts.close()


def test_connector_pins_the_created_or_switched_tab(monkeypatch):
    client = connector.Connector()
    client.bound_session = "sess-pool"
    monkeypatch.setattr(client, "attach", lambda **_: ({}, {"session_id": "sess-pool"}))
    sent = []

    def respond(record, method, path, payload=None, headers=None, timeout=10):
        sent.append((path, headers.get("X-Mixar-Session-Id")))
        name = payload["params"]["name"]
        result = ({"scenes": [{"name": "Pool", "session": "sess-pool"},
                              {"name": "Classroom", "session": "sess-new"}]}
                  if name == "mixar_scenes" else {"name": "Classroom", "session": "sess-new"})
        envelope = {"result": result, "usage": {}}
        return {"result": {"content": [{"type": "text", "text": ""}], "structuredContent": envelope,
                           "isError": False}}

    monkeypatch.setattr(connector, "request", respond)
    created = client.call("mixar_scene_new", {"name": "Classroom"}, str(uuid4()))
    assert sent[-1] == ("/ui", "") and client.bound_session == "sess-new"
    assert created["structuredContent"]["result"]["bound_session"] == "sess-new"
    listed = client.call("mixar_scenes", {}, str(uuid4()))["structuredContent"]["result"]["scenes"]
    assert [scene["bound"] for scene in listed] == [False, True]


@pytest.fixture
def gate(monkeypatch):
    import importlib
    window = SimpleNamespace(modal_operators=[])
    wm = SimpleNamespace(windows=[window], mixar_window_resizing=False)
    monkeypatch.setattr(scene_tabs.bpy, "context", SimpleNamespace(window_manager=wm), raising=False)
    busy = importlib.import_module("mixar.modules.common.render_coordinator.core")
    ownership = importlib.import_module("mixar.modules.common.ui_control.core.ownership")
    monkeypatch.setattr(busy, "busy", lambda: False)
    monkeypatch.setattr(ownership, "active", lambda: False)
    return window


def test_another_tabs_agent_does_not_block_a_new_tab(gate):
    """Mixie working in one tab holds the viewport lock and undo shield; a new
    tab is still allowed, as with the drawer's "+ New scene"."""
    gate.modal_operators = [SimpleNamespace(bl_idname="MIXAR_OT_agent_viewport_block"),
                            SimpleNamespace(bl_idname="MIXIE_CHAT_OT_undo_shield")]
    scene_tabs._gate()


def test_an_operation_the_user_has_open_blocks_a_tab_change(gate):
    gate.modal_operators = [SimpleNamespace(bl_idname="MIXAR_OT_agent_viewport_block"),
                            SimpleNamespace(bl_idname="TRANSFORM_OT_translate")]
    with pytest.raises(UIError, match="finish or cancel"):
        scene_tabs._gate()
