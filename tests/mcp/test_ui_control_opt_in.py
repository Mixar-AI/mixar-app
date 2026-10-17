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


def test_the_dialog_has_the_opt_in_switch():
    sheet = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect_sheet_ui.py").read_text()
    assert '"mixar.set_mcp_ui_control"' in sheet and "Let AI apps control Mixar's interface" in sheet


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
    assert "connect_sheet_ui.draw_dialog" in draw and "_signed_in(context)" in draw and "_ready(context)" in draw
    plans = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect_sheet_plans.py").read_text()
    assert "if not signed_in:\n        return SignedOutPlan" in plans and "ui.OP_LOGIN" in plans


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
    """A stock-widget layout (no sheet painters): records labels and each
    operator button's text and the properties the dialog set on it."""

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

    def row(self, *a, **kw):
        return self

    column = box = split = row

    def separator(self, *a, **kw):
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


READY = "MCP is on · AI apps can connect to this Mixar"
NOT_READY = "MCP is on · AI apps can use Mixar once it's signed in and connected"
OFF = "MCP is off · AI apps report Mixar as not connected"
SIGN_IN = "Sign in to connect MCP."


def _wm(signed_in):
    """``signed_in``: "yes", "expired" (an account whose session ended) or "out"."""
    return SimpleNamespace(window_manager=SimpleNamespace(
        mixie_chat_is_logged_in=signed_in != "out", mixie_chat_session_expired=signed_in == "expired",
        mixar_mcp_dialog_state='IDLE', mixar_mcp_dialog_app='CLAUDE_CODE', mixar_mcp_dialog_format='JSON',
        mixar_mcp_last_error='', mixar_mcp_result_app='', mixar_mcp_result_status=''))


def _draw_dialog(monkeypatch, *, enabled=True, running=True, connected=True, signed_in="yes"):
    from mixar.modules.mcp_bridge.ui.operators import connect, connect_sheet_plans
    monkeypatch.setattr(connect.runtime, "enabled", lambda: enabled)
    monkeypatch.setattr(connect.runtime, "is_running", lambda: running)
    monkeypatch.setattr(connect.runtime, "snapshot", lambda: {"connected": connected})
    monkeypatch.setattr(connect.runtime, "ui_control_enabled", lambda: False)
    monkeypatch.setattr(connect_sheet_plans, "stable_launch", lambda: ("mixar-mcp", []))
    log = []
    layout = _Layout(log)
    context = _wm(signed_in)
    _dialog_draw(connect)(SimpleNamespace(layout=layout, app="CLAUDE_CODE"), context)
    return layout, [entry[1] for entry in log if entry[0] == "label"]


def _switches(layout):
    return [props for idname, _icon, props in layout.buttons if idname == "mixar.set_mcp_enabled"]


@pytest.mark.parametrize("enabled", [True, False])
def test_a_signed_out_user_can_still_turn_mcp_off(monkeypatch, enabled):
    layout, labels = _draw_dialog(monkeypatch, enabled=enabled, running=enabled, signed_in="expired")
    assert ("operator", "mixie_chat.login", "Sign in") in layout.log and SIGN_IN in labels
    if enabled:  # Only the "off" direction is offered without an account.
        assert [props.enabled for props in _switches(layout)] == [False]
        assert ("operator", "mixar.set_mcp_enabled", "Turn off") in layout.log
    else:
        assert not _switches(layout)


@pytest.mark.parametrize("enabled, running", [(True, True), (True, False), (False, False)])
def test_the_mcp_status_line_spells_out_what_ai_apps_see(monkeypatch, enabled, running):
    """A "Disable" button beside an "MCP enabled" tick was pressed by a user
    trying to fix a connection, who then saw no sign that MCP was off (2026-10-05).
    The status line says what AI apps see right now and its one pill names
    the direction it switches."""
    layout, labels = _draw_dialog(monkeypatch, enabled=enabled, running=running)
    [props] = _switches(layout)
    assert props.enabled is (not enabled)
    texts = [entry[2] for entry in layout.log if entry[0] == "operator" and entry[1] == "mixar.set_mcp_enabled"]
    assert texts == (["Turn off"] if enabled else ["Turn on"])
    assert not any(entry[0] == "operator" and entry[2] in ("Disable", "Enable MCP") for entry in layout.log)
    expected = OFF if not enabled else READY if running else NOT_READY
    assert expected in labels and {READY, NOT_READY, OFF} - {expected} == {READY, NOT_READY, OFF} - set(labels)


@pytest.mark.parametrize("signed_in", ["yes", "expired", "out"])
@pytest.mark.parametrize("running", [True, False])
@pytest.mark.parametrize("connected", [True, False])
def test_the_dialog_says_ai_apps_can_connect_only_when_they_can(monkeypatch, signed_in, running, connected):
    """The relay runs without a session and refuses every call, and refuses
    scene calls while the agent server is down: the dialog once said "AI apps
    can connect" under its own "Sign in to Mixar" notice."""
    _layout, labels = _draw_dialog(monkeypatch, running=running, connected=connected, signed_in=signed_in)
    ready = signed_in == "yes" and running and connected
    assert (READY in labels) is ready
    assert (NOT_READY in labels) is (not ready)
    assert (SIGN_IN in labels) is (signed_in != "yes")
