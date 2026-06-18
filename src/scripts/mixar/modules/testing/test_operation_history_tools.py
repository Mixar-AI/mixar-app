# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.tools (agent read surface)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from types import SimpleNamespace

from mixar.modules.operation_history.core import tools, store, record
from mixar.modules.operation_history import constants as C


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv(C.ENV_BASE_DIR, str(tmp_path))
    store.reset_cache()
    store.append_operation(record.build_manual_record(
        scene_delta={"created": ["Cube"], "modified": [], "deleted": []},
        op_idname="object.add", label="User: object.add",
        affected={"objects": ["Cube"], "materials": [], "layers": []}, session_id="s1"))
    store.append_operation(record.build_agent_record(
        tool_name="scene_overview", result_dict={"success": True}, session_id="s1"))
    store.append_operation(record.build_agent_record(
        tool_name="execute_bpy_script", result_dict={"success": True, "modified_objects": ["Cube"]},
        session_id="s1"), script_text="import bpy\n")
    return SimpleNamespace(mixie_session_id="s1")


def test_summary(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    out = tools.run_tool(scene, "operation_history_summary", {})
    assert out["total"] == 3
    assert out["by_source"]["AGENT"] == 2
    assert out["by_kind"]["query"] == 1


def test_list_defaults_to_operations(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    out = tools.run_tool(scene, "list_operations", {})
    kinds = {o["kind"] for o in out["operations"]}
    assert kinds == {"operation"}            # query excluded by default
    out2 = tools.run_tool(scene, "list_operations", {"include_queries": True})
    assert any(o["kind"] == "query" for o in out2["operations"])


def test_get_operation_returns_script(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    out = tools.run_tool(scene, "get_operation", {"seq": 3})
    assert out["tool_name"] == "execute_bpy_script"
    assert "import bpy" in out["script"]


def test_operations_for_object(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    out = tools.run_tool(scene, "operations_for_object", {"object_name": "Cube"})
    assert out["count"] == 2          # add + modify


def test_unknown_tool(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    out = tools.run_tool(scene, "nope", {})
    assert "error" in out and "available" in out
