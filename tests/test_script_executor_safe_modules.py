# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression coverage for local-compute modules exposed to agent scripts."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"


def _load_executor_module(monkeypatch):
    packages = (
        ("mixar", _MIXAR_ROOT),
        ("mixar.modules", _MODULES_ROOT),
        ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
    )
    for name, path in packages:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)

    module_name = "mixar.modules.space_mixie_chat.core.executor"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / "executor.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def executor(monkeypatch):
    for module_name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, module_name, MagicMock(name=module_name))
    return _load_executor_module(monkeypatch).ScriptExecutor()


def test_hashlib_and_struct_are_available_to_sandboxed_scripts(executor):
    result = executor.execute(
        "\n".join(
            (
                "import hashlib",
                "import struct",
                "__RESULT__ = {",
                "    'digest': hashlib.sha256(b'mixar').hexdigest(),",
                "    'packed_hex': struct.pack('<I', 7).hex(),",
                "}",
            )
        ),
        push_undo=False,
    )

    assert result.success is True
    assert result.return_value == {
        "digest": "f619df0878494f0516c24c22bc0e8b964db1c9bddf6d74178e4ce1a629cd2cc0",
        "packed_hex": "07000000",
    }


def test_new_safe_modules_do_not_open_arbitrary_imports(executor):
    result = executor.execute("import os", push_undo=False)

    assert result.success is False
    assert "Module 'os' is not available" in (result.error or "")


@pytest.mark.parametrize("stage", ["_capture_scene_state", "_snapshot_handlers", "_detect_changes",
                                   "_cleanup_handlers", "note_turn_mode"])
def test_executor_failure_releases_lock_and_restores_output(executor, monkeypatch, stage):
    original = getattr(executor, stage)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    monkeypatch.setattr(executor, stage, MagicMock(side_effect=RuntimeError("injected")))
    with pytest.raises(RuntimeError, match="injected"):
        executor.execute("__RESULT__ = 7", push_undo=False)
    assert not executor._execution_lock.locked()
    assert sys.stdout is original_stdout and sys.stderr is original_stderr
    monkeypatch.setattr(executor, stage, original)
    assert executor.execute("__RESULT__ = 8", push_undo=False).return_value == 8


def test_bpy_ops_script_namespace_is_denied(executor):
    # SCRIPT_OT_python_file_run (stock Blender + the Mixar fork) executes an
    # arbitrary .py file with REAL builtins, bypassing the sandbox — so the
    # injected bpy.ops surface must deny the whole script.* namespace.
    result = executor.execute(
        "bpy.ops.script.python_file_run(filepath='/tmp/evil.py')",
        push_undo=False,
    )
    assert result.success is False
    assert "bpy.ops.script is not available" in (result.error or "")

    getattr_result = executor.execute(
        "getattr(bpy.ops, 'script')", push_undo=False
    )
    assert getattr_result.success is False
    assert "bpy.ops.script is not available" in (getattr_result.error or "")

    import_result = executor.execute(
        "\n".join((
            "import bpy",
            "bpy.ops.script.python_file_run(filepath='/tmp/evil.py')",
        )),
        push_undo=False,
    )
    assert import_result.success is False
    assert "bpy.ops.script is not available" in (import_result.error or "")


def test_bpy_data_surface_still_reachable_through_proxy(executor):
    # Legit operator access is forwarded: data/ops namespaces other than
    # script.* must keep working for sandboxed scripts.
    result = executor.execute(
        "\n".join((
            "__RESULT__ = {",
            "    'ops_mesh_ns': hasattr(bpy.ops, 'mesh'),",
            "    'ops_ed_ns': hasattr(bpy.ops, 'ed'),",
            "    'data_ns': hasattr(bpy, 'data'),",
            "    'context_ns': hasattr(bpy, 'context'),",
            "}",
        )),
        push_undo=False,
    )
    assert result.success is True
    assert result.return_value == {
        "ops_mesh_ns": True,
        "ops_ed_ns": True,
        "data_ns": True,
        "context_ns": True,
    }


def test_globals_returns_filtered_snapshot_for_transaction_guard(executor):
    result = executor.execute(
        "\n".join(
            (
                "__MERGE_BODY__ = True",
                "scope = globals()",
                "scope['injected_only_into_copy'] = True",
                "__RESULT__ = {",
                "    'merge_body': scope.get('__MERGE_BODY__'),",
                "    'has_builtins': '__builtins__' in scope,",
                "    'has_open': 'open' in scope,",
                "    'copy_did_not_mutate_globals': 'injected_only_into_copy' not in globals(),",
                "}",
            )
        ),
        push_undo=False,
    )

    assert result.success is True
    assert result.return_value == {
        "merge_body": True,
        "has_builtins": False,
        "has_open": False,
        "copy_did_not_mutate_globals": True,
    }


@pytest.mark.parametrize('failure', [AttributeError, RuntimeError, ValueError])
@pytest.mark.parametrize('failed_index', [0, 1])
@pytest.mark.parametrize('failed_phases', [{0}, {1}, {0, 1}])
def test_fingerprint_failure_preserves_inventory_and_known_edits(
        executor, monkeypatch, failure, failed_index, failed_phases):
    from copy import deepcopy
    from types import SimpleNamespace as NS

    module = sys.modules[executor.__class__.__module__]
    objects = [NS(name=name, type='EMPTY', location=(0, 0, 0),
                  rotation_euler=(0, 0, 0), scale=(1, 1, 1), material_slots=[])
               for name in ('first', 'middle', 'last')]
    monkeypatch.setattr(module, 'bpy', NS(data=NS(objects=objects, materials=[NS(name='Mat')])))
    phase = 0
    changed = False

    def fingerprint(obj, cache):
        if obj is objects[failed_index] and phase in failed_phases:
            raise failure('injected unreadable RNA')
        return 'edited' if changed and obj.name == 'last' else 'original'

    from mixar.modules.space_mixie_chat.core import executor_scene_state
    monkeypatch.setattr(executor_scene_state, 'bpy', module.bpy)
    monkeypatch.setattr(executor_scene_state, 'animation_fingerprint', fingerprint)
    before = executor._capture_scene_state()
    phase = 1
    after = executor._capture_scene_state()
    for state in (before, after):
        assert set(state['objects']) == {'first', 'middle', 'last'}
        assert state['materials'] == {'Mat'}
    saved = deepcopy((before, after))
    assert executor._detect_changes(before, after) == {'created': [], 'deleted': [], 'modified': []}
    assert (before, after) == saved
    objects[failed_index].location = (1, 0, 0)
    changed = True
    changes = executor._detect_changes(before, executor._capture_scene_state())
    assert set(changes['modified']) == {objects[failed_index].name, 'last'}
    assert not changes['created'] and not changes['deleted']
    removed = objects.pop(2)
    objects.append(NS(name='new', type='EMPTY', location=(0, 0, 0),
                      rotation_euler=(0, 0, 0), scale=(1, 1, 1), material_slots=[]))
    changes = executor._detect_changes(before, executor._capture_scene_state())
    assert changes['created'] == ['new'] and changes['deleted'] == [removed.name]


@pytest.mark.parametrize("script, scans", [
    ("__RESULT__ = len(bpy.data.objects)", False),
    ("ob = bpy.data.objects['A']\nob.location.x = 1.0", False),
    ("dg = bpy.context.evaluated_depsgraph_get()\n__RESULT__ = 1", True),
    ("ev = obj.evaluated_get(dg)", True),
    ("mesh.materials.append(mat.original)", True),
    ("bpy.data.meshes.new_from_object(o)", True),
])
def test_the_evaluated_material_scan_runs_only_after_scripts_that_touch_evaluated_data(
        executor, monkeypatch, script, scans):
    # The scan walks every material slot in the file; a script that never
    # named evaluated data cannot have stored an evaluated material.
    module = sys.modules[executor.__class__.__module__]
    calls = []
    monkeypatch.setattr(module, "restore_original_materials", lambda: calls.append(1) or 0)
    executor.execute(script, push_undo=False)
    assert bool(calls) is scans


@pytest.mark.parametrize("tail", ["raise RuntimeError('script failed mid-edit')",
                                  "__RESULT__ = len(bm.faces)"])
def test_edit_meshes_are_refreshed_even_after_a_bmesh_script_that_raised(executor, monkeypatch, tail):
    # A script that grew the live edit BMesh and then raised never reached
    # update_edit_mesh; the next redraw would read its stale loop triangles
    # (extract_tris_bmesh). The refresh lives in the executor's `finally`.
    module = sys.modules[executor.__class__.__module__]
    calls = []
    monkeypatch.setattr(module, "refresh_edit_meshes", lambda: calls.append(1) or 1)
    result = executor.execute("\n".join((
        "import bmesh",
        "bm = bmesh.from_edit_mesh(bpy.context.object.data)",
        "bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=4)",
        tail,
    )), push_undo=False)
    assert result.success is tail.startswith("__RESULT__"), result.error
    assert calls == [1]


@pytest.mark.parametrize("tail", ["raise RuntimeError('script failed after growing the mesh')",
                                  "__RESULT__ = len(me.loops)"])
def test_meshes_a_script_resized_are_repaired_even_when_it_raised(executor, monkeypatch, tail):
    # A script that grew a mesh through the data API can leave out-of-range
    # corner/edge indices; the next draw faults natively (count_indices,
    # calc_face_tri_starts_mesh). The repair lives in the executor's `finally`
    # and is reported to the agent.
    module = sys.modules[executor.__class__.__module__]
    snapshots, repairs = [], []
    monkeypatch.setattr(module, "snapshot_mesh_sizes", lambda: snapshots.append(1) or {"m": 1})
    monkeypatch.setattr(module, "repair_changed_meshes",
                        lambda before: repairs.append(before) or ["Grown"])
    result = executor.execute("\n".join((
        "me = bpy.data.meshes['Grown']",
        "me.loops.add(24)",
        tail,
    )), push_undo=False)
    assert result.success is tail.startswith("__RESULT__"), result.error
    assert snapshots == [1] and repairs == [{"m": 1}]
    assert "repaired invalid mesh topology" in result.output and "'Grown'" in result.output


def test_a_script_rejected_before_exec_validates_no_mesh(executor, monkeypatch):
    module = sys.modules[executor.__class__.__module__]
    repairs = []
    monkeypatch.setattr(module, "repair_changed_meshes", lambda before: repairs.append(before) or [])
    result = executor.execute("x = ().__class__.__bases__[0].__subclasses__()", push_undo=False)
    assert result.success is False
    assert repairs == [None]
