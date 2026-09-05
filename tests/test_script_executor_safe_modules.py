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
