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
