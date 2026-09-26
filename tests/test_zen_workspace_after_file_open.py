# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opening a .blend never leaks its layout into Zen Mode.

Loading a file with its UI replaces every workspace. Engine Mode keeps the
file's workspaces; the missing Zen Mode workspace is appended from the
bundled startup file (never duplicated from the file's own layout), and a
Zen user is switched back to it after the load.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.bootstrap import workflow_module
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME
from mixar.modules.workflow.core import workspace_loader


class _Workspaces(dict):
    def __iter__(self):
        return iter(self.values())


def _ws(name):
    return SimpleNamespace(name=name, object_mode="OBJECT", screens=[])


@pytest.fixture
def blend(monkeypatch, tmp_path):
    factory = tmp_path / "startup.mixar"
    factory.write_bytes(b"")
    layout = _ws("Layout")
    workspaces = _Workspaces(Layout=layout)
    window = SimpleNamespace(workspace=layout)
    duplicate = MagicMock()

    @contextmanager
    def load(path, link):
        assert path == str(factory) and link is False
        data_to = SimpleNamespace(workspaces=[])
        yield SimpleNamespace(workspaces=[BASIC_WORKSPACE_NAME, "Layout"]), data_to
        data_to.workspaces = [_ws(name) for name in data_to.workspaces]
        for ws in data_to.workspaces:
            workspaces[ws.name] = ws

    bpy = workspace_loader.bpy
    monkeypatch.setattr(bpy, "data", SimpleNamespace(
        workspaces=workspaces, libraries=SimpleNamespace(load=load)))
    monkeypatch.setattr(bpy, "context", SimpleNamespace(
        window=window, window_manager=SimpleNamespace(windows=[window])))
    monkeypatch.setattr(bpy, "ops", SimpleNamespace(
        workspace=SimpleNamespace(duplicate=duplicate)))
    monkeypatch.setattr(bpy, "utils", SimpleNamespace(
        system_resource=lambda kind, path: str(factory)))
    return SimpleNamespace(workspaces=workspaces, window=window, duplicate=duplicate)


def test_missing_zen_is_appended_from_factory_not_duplicated(blend):
    assert workspace_loader.ensure_basic_workspace() is True

    assert BASIC_WORKSPACE_NAME in blend.workspaces
    blend.duplicate.assert_not_called()
    assert blend.window.workspace.name == "Layout"


def test_zen_user_returns_to_zen_after_opening_a_file(blend, monkeypatch):
    monkeypatch.setattr(workspace_loader, "get_ui_mode", lambda: workspace_loader.UI_MODE_AI)

    assert workspace_loader.restore_zen_after_file_open() is True

    assert blend.window.workspace is blend.workspaces[BASIC_WORKSPACE_NAME]


def test_engine_user_keeps_the_files_workspaces(blend, monkeypatch):
    monkeypatch.setattr(workspace_loader, "get_ui_mode", lambda: workspace_loader.UI_MODE_PRO)

    assert workspace_loader.restore_zen_after_file_open() is False

    assert BASIC_WORKSPACE_NAME not in blend.workspaces
    assert blend.window.workspace.name == "Layout"


def test_load_post_defers_restore_only_for_real_files(monkeypatch):
    registered = []
    timers = SimpleNamespace(
        is_registered=lambda fn: fn in registered,
        register=lambda fn, first_interval=0.0: registered.append(fn),
    )
    bpy = workflow_module.bpy
    monkeypatch.setattr(bpy, "app", SimpleNamespace(timers=timers))
    monkeypatch.setattr(workflow_module, "configure_basic_workspace_chrome", lambda: None)
    monkeypatch.setattr(workflow_module, "_schedule_object_mode_reset", lambda: None)

    monkeypatch.setattr(bpy, "data", SimpleNamespace(filepath=""))
    workflow_module._on_load_post(None)
    assert workflow_module._restore_zen_after_load not in registered

    monkeypatch.setattr(bpy, "data", SimpleNamespace(filepath="/tmp/scene.blend"))
    workflow_module._on_load_post(None)
    assert workflow_module._restore_zen_after_load in registered
