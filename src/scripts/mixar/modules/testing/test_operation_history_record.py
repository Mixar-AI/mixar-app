# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.record (pure data model + builders)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from mixar.modules.operation_history.core import record as R
from mixar.modules.operation_history import constants as C


def test_derive_kind():
    assert R.derive_kind("get_operation_history") == C.KIND_META
    assert R.derive_kind("scene_overview") == C.KIND_QUERY
    assert R.derive_kind("execute_bpy_script") == C.KIND_OPERATION
    assert R.derive_kind("unknown") == C.KIND_OPERATION


def test_category_for_operator():
    assert R.category_for_operator("transform.translate") == C.CAT_TRANSFORM
    assert R.category_for_operator("object.delete") == C.CAT_OBJECT
    assert R.category_for_operator("material.new") == C.CAT_MATERIAL
    assert R.category_for_operator("ed.undo") == C.CAT_UNDO
    assert R.category_for_operator(None) == C.CAT_OTHER


def test_build_agent_record_maps_result_dict():
    rec = R.build_agent_record(
        tool_name="execute_bpy_script",
        result_dict={"success": True, "created_objects": ["Cube"], "modified_objects": []},
        session_id="s1", instance_id="i1", request_id="srv_1",
    )
    assert rec.source == C.SOURCE_AGENT
    assert rec.kind == C.KIND_OPERATION
    assert rec.tool_name == "execute_bpy_script"
    assert rec.scene_delta["created"] == ["Cube"]
    assert rec.success is True
    assert rec.id and rec.ts > 0          # finalized


def test_build_agent_record_query_has_empty_delta():
    rec = R.build_agent_record(
        tool_name="scene_overview",
        result_dict={"success": True}, session_id="s1",
    )
    assert rec.kind == C.KIND_QUERY
    assert rec.category == C.CAT_QUERY
    assert rec.scene_delta == {"created": [], "modified": [], "deleted": []}


def test_build_manual_record():
    rec = R.build_manual_record(
        scene_delta={"created": [], "modified": ["Cube"], "deleted": []},
        op_idname="transform.translate", label="User: transform.translate",
        category=C.CAT_TRANSFORM, affected={"objects": ["Cube"], "materials": [], "layers": []},
        session_id="s1",
    )
    assert rec.source == C.SOURCE_USER
    assert rec.kind == C.KIND_OPERATION
    assert rec.op_idname == "transform.translate"
    assert rec.to_dict()["category"] == C.CAT_TRANSFORM
