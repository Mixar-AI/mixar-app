# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.capture_service.

Two paths are exercised: the pure decision helper ``should_capture`` and one
integration of ``_capture_tick`` driven through a fake ``bpy`` context + a
monkeypatched store (the real diff/attribution/record builders still run; only
the disk I/O is faked). The depsgraph/timer wiring itself is exercised inside
Blender.

``capture_service`` does a module-top ``from bpy.app.handlers import
persistent`` (and transitively pulls in the chat session manager → auth →
keyring) which the bare root ``conftest.py`` bpy stub does not satisfy, so we
install the test bpy mock (``mock_bpy.install_bpy_mock``), which registers
``bpy.app.handlers`` with an identity ``persistent`` decorator and stubs the
third-party modules, before importing the module under test.
"""

import os
import sys
from types import SimpleNamespace

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.operation_history.constants import (
    CAT_TRANSFORM, SOURCE_USER,
)
from mixar.modules.operation_history.core import capture_service as CS
from mixar.modules.space_mixie_chat.constants import SessionState


def test_should_capture_only_idle():
    assert CS.should_capture(SessionState.IDLE) is True
    assert CS.should_capture(SessionState.BUSY) is False
    assert CS.should_capture(SessionState.MODIFYING) is False
    assert CS.should_capture(SessionState.AWAITING_INPUT) is False
    assert CS.should_capture(SessionState.OFFLINE) is False


def _fake_obj(name, loc=(0.0, 0.0, 0.0)):
    return SimpleNamespace(
        name=name, type="MESH", location=loc,
        rotation_euler=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
        material_slots=[],
    )


def test_capture_tick_records_manual_op_when_idle(monkeypatch):
    """Integration: dirty + IDLE + a new object → exactly one USER record."""
    sid = "sess-abc"
    captured = []

    # Module globals are not auto-undone by monkeypatch; reset them by hand.
    CS._prev.clear()
    CS._last_op.clear()
    # Seed a baseline with no objects so the new object reads as "created".
    CS._prev[sid] = {"objects": {}}

    scene = SimpleNamespace(mixie_session_id=sid, objects=[_fake_obj("Cube")])
    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="transform.translate", as_pointer=lambda: 42),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.IDLE),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    monkeypatch.setattr(CS, "_dirty", True)

    assert CS._capture_tick() == 0.5
    assert len(captured) == 1
    rec = captured[0]
    assert rec.source == SOURCE_USER
    assert rec.op_idname == "transform.translate"
    assert rec.category == CAT_TRANSFORM
    assert "Cube" in rec.scene_delta["created"]
    assert "Cube" in rec.affected["objects"]


def test_capture_tick_skips_when_not_idle(monkeypatch):
    """Gating: a BUSY session refreshes the baseline but records nothing."""
    sid = "sess-busy"
    captured = []

    CS._prev.clear()
    CS._last_op.clear()
    CS._prev[sid] = {"objects": {}}

    scene = SimpleNamespace(mixie_session_id=sid, objects=[_fake_obj("Cube")])
    wm = SimpleNamespace(operators=[])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.BUSY),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    monkeypatch.setattr(CS, "_dirty", True)

    assert CS._capture_tick() == 0.5
    assert captured == []
    # Baseline kept fresh so the busy-window change is not later misattributed.
    assert "Cube" in CS._prev[sid]["objects"]
