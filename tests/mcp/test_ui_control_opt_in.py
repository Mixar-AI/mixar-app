# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Driving Mixar's interface is opt-in; scene, project and status tools never are."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client

from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.common.ui_control.core import schema, service
from mixar.modules.mcp_bridge.core import runtime, stdio_server


def test_interface_input_is_refused_until_the_user_allows_it(monkeypatch):
    monkeypatch.setattr(runtime, "ui_control_enabled", lambda: False)
    for name in sorted(schema.UI_INPUT):
        request = SimpleNamespace(name=name, args={}, session="", owner="o", deadline=0)
        with pytest.raises(UIError, match="Let AI apps control Mixar's interface"):
            next(service._run(request))
    assert "mixar_ui_context" not in schema.UI_INPUT and "mixar_scene_new" not in schema.UI_INPUT


def test_the_preference_needs_mcp_and_an_explicit_yes(monkeypatch):
    config = {}
    monkeypatch.setattr(runtime, "get_config", lambda: config)
    assert runtime.ui_control_enabled() is False
    config.update(mcp_enabled=True)
    assert runtime.ui_control_enabled() is False
    config.update(mcp_ui_control=True)
    assert runtime.ui_control_enabled() is True


class Connector:
    def __init__(self, ui_control):
        self.tasks, self.health = set(), {"ui_control": ui_control}

    def catalog(self):
        return [{"name": "scene_overview", "description": "Scene.", "inputSchema": {"type": "object"},
                 "_meta": {"mixar/domain": "scene"}}]

    def cancel(self, call_id=None):
        pass


@pytest.mark.parametrize("allowed", [True, False])
def test_the_launcher_advertises_interface_tools_only_when_allowed(allowed):
    async def main():
        async with Client(stdio_server.create_server(Connector(allowed))) as client:
            return {tool.name for tool in (await client.list_tools()).tools}
    names = asyncio.run(main())
    assert (schema.UI_INPUT <= names) is allowed
    assert {"scene_overview", "mixar_ui_context", "mixar_scenes", "mixar_project_open"} <= names


def test_signin_restored_after_a_load_is_reported_as_temporary(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import auth_ops
    monkeypatch.setattr(runtime, "enabled", lambda: True)
    wm = SimpleNamespace(mixie_chat_is_logged_in=False, mixie_chat_session_expired=False)
    monkeypatch.setattr(service, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    monkeypatch.setattr(auth_ops, "_auth_check_started", True, raising=False)
    with pytest.raises(UIError, match="restoring your sign-in"):
        service._signed_in()
    monkeypatch.setattr(auth_ops, "_auth_check_started", False)
    with pytest.raises(UIError, match="Sign in to Mixar"):
        service._signed_in()


def test_the_dialog_has_the_opt_in_checkbox():
    dialog = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect.py").read_text()
    assert '"mixar.set_mcp_ui_control"' in dialog and "Let AI apps control Mixar's interface" in dialog


def test_a_vanished_scene_points_the_agent_to_rebinding(monkeypatch):
    """After File > New the connection's scene no longer exists anywhere."""
    from mixar.modules.common.ui_control.core import observe
    monkeypatch.setattr(runtime, "ui_control_enabled", lambda: True)
    shown = SimpleNamespace(mixie_session_id="new-doc")
    monkeypatch.setattr(observe, "main_window", lambda: SimpleNamespace(scene=shown))
    monkeypatch.setattr(service, "bpy", SimpleNamespace(data=SimpleNamespace(scenes=[shown])))
    request = SimpleNamespace(name="mixar_ui_observe", args={}, session="old-doc", owner="o", deadline=0)
    with pytest.raises(UIError, match="mixar_ui_context\\(session=") as gone:
        next(service._run(request))
    assert gone.value.result()["error_type"] == "document_changed"


def test_an_action_that_loads_a_document_reports_it_instead_of_unknown(monkeypatch):
    finished = []
    monkeypatch.setattr(service, "_registered", True)
    monkeypatch.setattr(service.ownership, "active", lambda: False)
    monkeypatch.setattr(service, "_finish", lambda req, result, **kw: finished.append((result, kw)) or req.done.set())
    request = service.Request("o", "mixar_ui_act", {}, "c", "", float("inf"))
    request.cancelled.set()
    request.document_loaded = True
    monkeypatch.setattr(service, "_active", (request, (step for step in ())))
    service._pump()
    assert finished[0][0]["document_loaded"] is True and "failed" not in finished[0][1]


def test_connecting_ai_apps_needs_a_signed_in_mixar():
    """MCP acts for the signed-in account, and the tool list it lists up front is
    saved while signed in, so every enabling path refuses a signed-out Mixar."""
    import ast
    from mixar.modules.mcp_bridge.ui.operators import connect
    signed_in = SimpleNamespace(window_manager=SimpleNamespace(mixie_chat_is_logged_in=True,
                                                               mixie_chat_session_expired=False))
    expired = SimpleNamespace(window_manager=SimpleNamespace(mixie_chat_is_logged_in=True,
                                                             mixie_chat_session_expired=True))
    reports = []
    op = SimpleNamespace(report=lambda kind, text: reports.append(text))
    assert connect._refuse_signed_out(op, signed_in) is False and not reports
    assert connect._refuse_signed_out(op, expired) is True and "Sign in" in reports[0]
    source = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect.py").read_text()
    tree = ast.parse(source)
    guarded = {node.name for node in tree.body if isinstance(node, ast.ClassDef)
               for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "execute"
               and "_refuse_signed_out" in ast.unparse(item)}
    assert {"MIXAR_OT_set_mcp_enabled", "MIXAR_OT_copy_mcp_setup", "MIXAR_OT_mcp_add_to_app"} <= guarded
    dialog = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MIXAR_OT_mcp_setup")
    draw = ast.unparse(next(item for item in dialog.body if isinstance(item, ast.FunctionDef) and item.name == "draw"))
    assert "mixie_chat.login" in draw and draw.index("_signed_in") < draw.index("_draw_switch")


def test_setup_saves_the_tool_list_at_once():
    source = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect.py").read_text()
    assert "tool_snapshot.forget()" in source and source.count("_save_tools_now()") >= 2


def test_mcp_setup_lives_in_the_profile_menu_not_help():
    root = Path(__file__).parents[2] / "src"
    assert not (root / "scripts/mixar/modules/mcp_bridge/ui/menus/help.py").exists()
    assert '"mixar.connect_ai"' in (root / "scripts/mixar/modules/space_mixie_chat/ui/topbar.py").read_text()
    card = (root / "source/blender/editors/interface/interface_mixar_profile_card.cc").read_text()
    assert '"MIXAR_OT_connect_ai"' in card and "MixarCardIcon::Plug" in card


class _Layout:
    """Records what a dialog draws: ``log`` entries, plus each operator button's
    icon and the properties the dialog set on it (``buttons``)."""

    def __init__(self, log):
        self.log, self.enabled, self.alignment = log, True, ""
        self.buttons = []

    def label(self, text="", **kw):
        self.log.append(("label", text))

    def operator(self, idname, text="", **kw):
        self.log.append(("operator", idname, text))
        props = SimpleNamespace()
        self.buttons.append((idname, kw.get("icon"), props))
        return props

    def row(self, **kw):
        return self

    column = box = row

    def separator(self):
        pass

    def prop(self, *a, **kw):
        pass


def _dialog_draw(connect):
    """The real draw method (operator classes are mocks under the stub bpy)."""
    import ast
    tree = ast.parse(Path(connect.__file__).read_text())
    dialog = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MIXAR_OT_mcp_setup")
    draw = next(item for item in dialog.body if isinstance(item, ast.FunctionDef) and item.name == "draw")
    namespace = dict(vars(connect))
    exec(compile(ast.fix_missing_locations(ast.Module([draw], [])), connect.__file__, "exec"), namespace)
    return namespace["draw"]


SWITCH = "Allow AI apps to use Mixar (MCP)"


def _switches(layout):
    return [(icon, props) for idname, icon, props in layout.buttons if idname == "mixar.set_mcp_enabled"]


@pytest.mark.parametrize("enabled", [True, False])
def test_a_signed_out_user_can_still_turn_mcp_off(monkeypatch, enabled):
    from mixar.modules.mcp_bridge.ui.operators import connect
    monkeypatch.setattr(connect.runtime, "enabled", lambda: enabled)
    monkeypatch.setattr(connect.runtime, "is_running", lambda: enabled)
    log = []
    layout = _Layout(log)
    dialog = SimpleNamespace(layout=layout)
    expired = SimpleNamespace(window_manager=SimpleNamespace(mixie_chat_is_logged_in=True,
                                                             mixie_chat_session_expired=True))
    _dialog_draw(connect)(dialog, expired)
    assert ("operator", "mixie_chat.login", "Sign In") in log
    switches = _switches(layout)
    if enabled:  # The switch is offered only in its "off" direction.
        assert ("operator", "mixar.set_mcp_enabled", SWITCH) in log
        assert [(icon, props.enabled) for icon, props in switches] == [("CHECKBOX_HLT", False)]
    else:
        assert not switches


@pytest.mark.parametrize("enabled, running", [(True, True), (True, False), (False, False)])
def test_the_mcp_switch_is_a_labelled_checkbox_with_its_state_spelled_out(monkeypatch, enabled, running):
    """A "Disable" button beside an "MCP enabled" tick was pressed by a user
    trying to fix a connection, who then saw no sign that MCP was off (2026-10-05).
    The switch is a checkbox that names what it allows, and a line under it
    says what AI apps see right now."""
    from mixar.modules.mcp_bridge.ui.operators import connect
    monkeypatch.setattr(connect.runtime, "enabled", lambda: enabled)
    monkeypatch.setattr(connect.runtime, "is_running", lambda: running)
    monkeypatch.setattr(connect.runtime, "ui_control_enabled", lambda: False)
    monkeypatch.setattr(connect, "stable_launch", lambda: ("mixar-mcp", []))
    log = []
    layout = _Layout(log)
    signed_in = SimpleNamespace(window_manager=SimpleNamespace(mixie_chat_is_logged_in=True,
                                                               mixie_chat_session_expired=False))
    _dialog_draw(connect)(SimpleNamespace(layout=layout, app="CLAUDE_CODE"), signed_in)
    [(icon, props)] = _switches(layout)
    assert icon == ("CHECKBOX_HLT" if enabled else "CHECKBOX_DEHLT") and props.enabled is (not enabled)
    assert not any(entry[0] == "operator" and entry[2] in ("Disable", "Enable MCP") for entry in log)
    labels = [text for kind, text in ((e[0], e[1]) for e in log) if kind == "label"]
    status = labels[labels.index("Your AI app can start Mixar when needed.") + 1]
    if not enabled:
        assert status.startswith("MCP is off:") and "not connected" in status
    elif running:
        assert status.startswith("MCP is on:")
    else:
        assert status.startswith("MCP is on,") and "waiting" in status
