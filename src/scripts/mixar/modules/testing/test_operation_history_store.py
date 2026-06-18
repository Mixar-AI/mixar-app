# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.store (local-dir I/O + record_operation)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import json  # noqa: E402,F401

from mixar.modules.operation_history.core import store, record  # noqa: E402
from mixar.modules.operation_history import constants as C  # noqa: E402


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv(C.ENV_BASE_DIR, str(tmp_path))
    store.reset_cache()


def test_append_then_read_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    rec = record.build_manual_record(scene_delta={"created": ["Cube"], "modified": [], "deleted": []},
                                     op_idname="object.add", label="add", session_id="s1")
    store.append_operation(rec)
    rows = store.read_operations("s1")
    assert len(rows) == 1
    assert rows[0]["op_idname"] == "object.add"
    assert rows[0]["seq"] == 1


def test_seq_increments_and_persists(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    for i in range(3):
        store.append_operation(record.build_manual_record(
            scene_delta=None, label="x", session_id="s1"))
    store.reset_cache()   # simulate restart; seq re-derived from file
    store.append_operation(record.build_manual_record(scene_delta=None, label="y", session_id="s1"))
    rows = store.read_operations("s1", limit=10)
    assert [r["seq"] for r in rows] == [1, 2, 3, 4]


def test_script_file_written_and_read(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    rec = record.build_agent_record(tool_name="execute_bpy_script",
                                    result_dict={"success": True}, session_id="s1")
    store.append_operation(rec, script_text="import bpy\nprint('hi')\n")
    rows = store.read_operations("s1")
    assert rows[0]["script_file"].startswith(C.SCRIPTS_SUBDIR + "/") or rows[0]["script_file"].startswith(C.SCRIPTS_SUBDIR + "\\")
    body = store.read_script("s1", seq=rows[0]["seq"])
    assert "print('hi')" in body


def test_read_filters(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    store.append_operation(record.build_agent_record(tool_name="scene_overview",
                           result_dict={"success": True}, session_id="s1"))   # kind=query
    store.append_operation(record.build_manual_record(
        scene_delta={"created": [], "modified": ["Cube"], "deleted": []},
        op_idname="transform.translate", label="move",
        affected={"objects": ["Cube"], "materials": [], "layers": []}, session_id="s1"))
    assert len(store.read_operations("s1", kind=C.KIND_OPERATION)) == 1
    assert len(store.read_operations("s1", source=C.SOURCE_USER)) == 1
    assert len(store.read_operations("s1", object_name="Cube")) == 1


def test_record_operation_public_api(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    store.record_operation("s1", "Layer added", category=C.CAT_LAYER)
    rows = store.read_operations("s1")
    assert rows[0]["label"] == "Layer added"
    assert rows[0]["category"] == C.CAT_LAYER
    assert rows[0]["source"] == C.SOURCE_USER
