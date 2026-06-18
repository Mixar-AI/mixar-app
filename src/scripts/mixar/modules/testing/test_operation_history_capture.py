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
    CAT_MATERIAL, CAT_OBJECT, CAT_TRANSFORM, SOURCE_USER,
)
from mixar.modules.operation_history.core import capture_service as CS
from mixar.modules.operation_history.core.scene_diff import snapshot_scene
from mixar.modules.space_mixie_chat.constants import SessionState


def test_should_capture_when_agent_not_busy():
    # Capture manual ops whenever the agent is NOT actively executing — including
    # before any chat session exists (OFFLINE/CONNECTING) and when idle.
    assert CS.should_capture(SessionState.IDLE) is True
    assert CS.should_capture(SessionState.OFFLINE) is True
    assert CS.should_capture(SessionState.CONNECTING) is True
    assert CS.should_capture(SessionState.AWAITING_INPUT) is True
    # ...but never while the agent is running (those are agent ops, captured elsewhere).
    assert CS.should_capture(SessionState.BUSY) is False
    assert CS.should_capture(SessionState.MODIFYING) is False


def test_depsgraph_mesh_update_marks_capture_dirty(monkeypatch):
    class Depsgraph:
        def id_type_updated(self, id_type):
            return id_type == "MESH"

    scene = SimpleNamespace(name="Scene")
    CS._dirty_scene_names.clear()
    monkeypatch.setattr(CS, "_dirty_context_scene", False)

    CS._on_depsgraph(scene, Depsgraph())

    assert CS._dirty_scene_names == {"Scene"}


def _mesh(vertices=0, edges=0, faces=0):
    return SimpleNamespace(vertices=list(range(vertices)), edges=list(range(edges)),
                           polygons=list(range(faces)))


def _fake_obj(name, loc=(0.0, 0.0, 0.0), mesh=None):
    return SimpleNamespace(
        name=name, type="MESH", location=loc,
        rotation_euler=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
        material_slots=[], data=mesh,
    )


def _fake_scene(name, sid, objects):
    return SimpleNamespace(name=name, mixar_op_history_id=sid, objects=objects)


def _mark_scene_dirty(monkeypatch, scene, *extra_scenes):
    CS._dirty_scene_names.clear()
    monkeypatch.setattr(CS, "_dirty_context_scene", False)
    scenes = {s.name: s for s in (scene,) + extra_scenes}
    monkeypatch.setattr(CS.bpy, "data", SimpleNamespace(scenes=scenes))
    CS._dirty_scene_names.add(scene.name)


def test_capture_tick_records_manual_op_when_idle(monkeypatch):
    """Integration: dirty + IDLE + a new object → exactly one USER record."""
    sid = "sess-abc"
    captured = []

    # Module globals are not auto-undone by monkeypatch; reset them by hand.
    CS._prev.clear()
    # Seed a baseline with no objects so the new object reads as "created".
    CS._prev[sid] = {"objects": {}, "materials": {}}

    scene = _fake_scene("Scene", sid, [_fake_obj("Cube")])
    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="transform.translate", as_pointer=lambda: 42),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.IDLE),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    _mark_scene_dirty(monkeypatch, scene)

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
    CS._prev[sid] = {"objects": {}, "materials": {}}

    scene = _fake_scene("Scene", sid, [_fake_obj("Cube")])
    wm = SimpleNamespace(operators=[])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.BUSY),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    _mark_scene_dirty(monkeypatch, scene)

    assert CS._capture_tick() == 0.5
    assert captured == []
    # Baseline kept fresh so the busy-window change is not later misattributed.
    assert "Cube" in CS._prev[sid]["objects"]


def test_capture_tick_uses_depsgraph_scene_not_context(monkeypatch):
    """A dirty scene from the depsgraph is captured even when context.scene differs."""
    sid = "sess-dirty-scene"
    captured = []

    CS._prev.clear()
    CS._prev[sid] = {"objects": {}, "materials": {}}

    context_scene = _fake_scene("ContextScene", "sess-context", [])
    dirty_scene = _fake_scene("DirtyScene", sid, [_fake_obj("Cube")])
    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="object.add", as_pointer=lambda: 71),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=context_scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.IDLE),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    _mark_scene_dirty(monkeypatch, dirty_scene, context_scene)

    assert CS._capture_tick() == 0.5
    assert len(captured) == 1
    rec = captured[0]
    assert rec.session_id == sid
    assert "Cube" in rec.scene_delta["created"]
    assert "sess-context" not in CS._prev


def test_offline_capture_then_read_roundtrip(monkeypatch, tmp_path):
    """Reproduces the live bug end-to-end: a manual edit made with NO chat session
    (state OFFLINE, no session id yet) is captured to the REAL store AND read back via the
    agent tool — proving capture and the read tool agree on the per-scene key."""
    from mixar.modules.operation_history.core import store, tools
    from mixar.modules.operation_history import constants as C

    monkeypatch.setenv(C.ENV_BASE_DIR, str(tmp_path))
    store.reset_cache()
    CS._prev.clear()

    scene = _fake_scene("OfflineScene", "", [])   # no session id assigned yet
    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="object.add", as_pointer=lambda: 7),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.OFFLINE),
    )

    # Tick 1: empty scene → establishes the baseline, records nothing (and lazily assigns
    # the scene's persistent history id).
    _mark_scene_dirty(monkeypatch, scene)
    CS._capture_tick()
    assert scene.mixar_op_history_id          # id was assigned during capture

    # User adds a Cube while still OFFLINE (before ever opening the chat).
    scene.objects = [_fake_obj("Cube")]
    _mark_scene_dirty(monkeypatch, scene)
    CS._capture_tick()

    # The agent later reads this scene's history — must find the manual edit.
    out = tools.run_tool(scene, "list_operations", {})
    assert out["count"] == 1
    rec = out["operations"][0]
    assert rec["source"] == SOURCE_USER
    assert "Cube" in rec["scene_delta"]["created"]


def test_awaiting_input_capture_then_read_roundtrip(monkeypatch, tmp_path):
    """A user can edit the scene while the agent waits for confirmation; that edit is
    manual user work and must not be silently folded into the baseline."""
    from mixar.modules.operation_history.core import store, tools
    from mixar.modules.operation_history import constants as C

    monkeypatch.setenv(C.ENV_BASE_DIR, str(tmp_path))
    store.reset_cache()
    CS._prev.clear()

    scene = _fake_scene("AwaitingScene", "awaiting-scene", [])
    CS._prev[scene.mixar_op_history_id] = {"objects": {}, "materials": {}}
    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="object.add", as_pointer=lambda: 9),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.AWAITING_INPUT),
    )

    scene.objects = [_fake_obj("Cube")]
    _mark_scene_dirty(monkeypatch, scene)
    CS._capture_tick()

    out = tools.run_tool(scene, "list_operations", {})
    assert out["count"] == 1
    rec = out["operations"][0]
    assert rec["source"] == SOURCE_USER
    assert "Cube" in rec["scene_delta"]["created"]


def test_capture_tick_records_material_edit(monkeypatch):
    """D2: a material node-tree edit (no object change) is captured as a MATERIAL op."""
    sid = "sess-mat"
    captured = []
    CS._prev.clear()

    mat = SimpleNamespace(name="Mat", node_tree=SimpleNamespace(nodes=[0, 1]))
    obj = SimpleNamespace(name="Cube", type="MESH", location=(0.0, 0.0, 0.0),
                          rotation_euler=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
                          material_slots=[SimpleNamespace(material=mat)])
    scene = _fake_scene("MaterialScene", sid, [obj])
    CS._prev[sid] = snapshot_scene(scene)        # baseline: Mat has 2 nodes
    mat.node_tree.nodes.append(2)                # user edits the material → 3 nodes

    wm = SimpleNamespace(operators=[])           # material edit routes through no REGISTER op
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.IDLE),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    _mark_scene_dirty(monkeypatch, scene)

    assert CS._capture_tick() == 0.5
    assert len(captured) == 1
    rec = captured[0]
    assert rec.category == CAT_MATERIAL
    assert "Mat" in rec.affected["materials"]
    assert rec.label == "User: edited material Mat (+1 node)"
    assert rec.scene_delta["created"] == [] and rec.scene_delta["modified"] == []


def test_capture_tick_records_extrude_like_mesh_topology_change(monkeypatch):
    """An edit-mode extrude may leave the last operator as transform.translate, but the
    mesh topology delta should still produce a descriptive operation-history record."""
    sid = "sess-extrude"
    captured = []
    CS._prev.clear()

    before_obj = _fake_obj("Cube", mesh=_mesh(8, 12, 6))
    scene = _fake_scene("ExtrudeScene", sid, [before_obj])
    CS._prev[sid] = snapshot_scene(scene)
    scene.objects = [_fake_obj("Cube", mesh=_mesh(12, 16, 7))]

    wm = SimpleNamespace(operators=[
        SimpleNamespace(bl_idname="transform.translate", as_pointer=lambda: 11),
    ])
    monkeypatch.setattr(CS.bpy, "context", SimpleNamespace(scene=scene, window_manager=wm))
    monkeypatch.setattr(
        CS, "get_session_manager",
        lambda: SimpleNamespace(get_state=lambda s: SessionState.IDLE),
    )
    monkeypatch.setattr(CS.store, "append_operation", lambda rec: captured.append(rec) or rec)
    _mark_scene_dirty(monkeypatch, scene)

    assert CS._capture_tick() == 0.5
    assert len(captured) == 1
    rec = captured[0]
    assert rec.category == CAT_OBJECT
    assert rec.label == "User: extruded or added mesh geometry to Cube (+4 vertices, +4 edges, +1 face)"
    assert rec.op_idname == "transform.translate"
    assert rec.scene_delta["modified"] == ["Cube"]
    assert rec.scene_delta["object_changes"]["Cube"]["mesh_delta"] == {
        "vertices": 4, "edges": 4, "faces": 1,
    }
    assert "Cube" in rec.affected["objects"]
