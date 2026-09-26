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

    monkeypatch.setattr(module, 'animation_fingerprint', fingerprint)
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
