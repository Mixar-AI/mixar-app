# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Copy Setup and Add to App when the per-user launcher cannot be written:
an error report naming its folder, CANCELLED, and nothing copied or added."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.mcp_bridge.ui.operators import connect


def _execute(cls_name, **overrides):
    """The real execute method (operator classes are mocks under the stub bpy)."""
    tree = ast.parse(Path(connect.__file__).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls_name)
    execute = next(item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "execute")
    namespace = dict(vars(connect), _refuse_signed_out=lambda op, context: False, _enable=lambda op: None)
    namespace.update(overrides)
    exec(compile(ast.fix_missing_locations(ast.Module([execute], [])), connect.__file__, "exec"), namespace)
    return namespace["execute"]


FOLDER = "/home/user/.mixar/connector"


@pytest.fixture
def logger(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(connect, "logger", logger)
    monkeypatch.setattr(connect.installation, "directory", lambda: FOLDER)
    return logger


def _op(reports, **props):
    return SimpleNamespace(report=lambda kind, text: reports.append((kind, text)), **props)


def _assert_reported(reports, logger):
    assert reports == [({'ERROR'}, f"Could not write Mixar's MCP launcher in {FOLDER}. Check that files there "
                                   "can be created and are not open in another program, then try again")]
    assert logger.warning.call_args.kwargs == {"exc_info": True}


def test_copy_leaves_the_clipboard_alone(logger):
    reports = []
    context = SimpleNamespace(window_manager=SimpleNamespace(clipboard="before"))
    execute = _execute("MIXAR_OT_copy_mcp_setup", connection_config=Mock(side_effect=PermissionError("denied")))
    assert execute(_op(reports, client="CODEX"), context) == {'CANCELLED'}
    assert context.window_manager.clipboard == "before"
    _assert_reported(reports, logger)


def test_add_starts_nothing(logger):
    reports = []
    app_add, connect_state = Mock(), Mock()
    execute = _execute("MIXAR_OT_mcp_add_to_app", launch=Mock(side_effect=PermissionError("denied")),
                       app_add=app_add, connect_state=connect_state)
    assert execute(_op(reports, app="CODEX"), SimpleNamespace(window_manager=SimpleNamespace())) == {'CANCELLED'}
    app_add.start.assert_not_called()
    connect_state.begin_add.assert_not_called()
    _assert_reported(reports, logger)
