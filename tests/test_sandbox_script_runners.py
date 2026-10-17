# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""bpy's script runners stay refused however they are spelled or reached.

Blender resolves ``bpy.ops.<ns>`` case-insensitively (the namespace is
uppercased into the operator idname, so ``bpy.ops.SCRIPT.python_file_run`` is
``SCRIPT_OT_python_file_run``), and its private module helpers are plain
functions with the real builtins: ``bpy.ops._op_create_function`` rebuilds any
operator from a string and ``bpy.utils._test_import(name, set())`` returns the
real module it imports. Both are checked through the proxies the executor and
the material registry hand to scripts, ``make_sandboxed_bpy(safe_module(bpy))``,
against a ``bpy`` shaped like Blender's own ``bpy/ops.py`` (a module-level
``__getattr__`` builds a fresh ``bpy.ops.<ns>`` module for ANY name).
"""

import importlib.util
from pathlib import Path
import sys
import types
from types import ModuleType

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"


def _load(monkeypatch, leaf):
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
    module_name = f"mixar.modules.space_mixie_chat.core.{leaf}"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / f"{leaf}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(monkeypatch):
    safe_module = _load(monkeypatch, "sandbox_modules").safe_module
    make_sandboxed_bpy = _load(monkeypatch, "sandbox_bpy").make_sandboxed_bpy
    return safe_module, make_sandboxed_bpy


def _fake_bpy():
    """Shaped like Blender's bpy/ops.py: ``bpy.ops.<ns>`` is a fresh module
    named ``bpy.ops.<ns>`` built by a module-level __getattr__ for any name,
    and the private helpers that build operators are plain module attributes."""
    calls = []

    def create_function(namespace, func):
        def operator(**kwargs):
            calls.append((namespace, func, kwargs))
            return {"FINISHED"}
        return operator

    def submodule(namespace):
        mod = ModuleType("bpy.ops." + namespace)
        mod.__getattr__ = lambda func: create_function(namespace, func)
        return mod

    ops = ModuleType("bpy.ops")
    ops._op_create_function = create_function
    ops._bpy_ops_submodule = submodule
    ops.__getattr__ = submodule

    utils = ModuleType("bpy.utils")
    utils._test_import = lambda name, loaded: __import__(name)
    utils.keyconfig_set = lambda filepath, report=None: None
    utils.user_resource = lambda *a, **k: "/tmp"

    bpy = ModuleType("bpy")
    bpy.ops = ops
    bpy.utils = utils
    bpy.types = ModuleType("bpy.types")
    bpy.context = types.SimpleNamespace()
    bpy.data = types.SimpleNamespace()
    bpy.app = types.SimpleNamespace(driver_namespace={})
    return bpy, calls


def _sandboxed(sandbox):
    safe_module, make_sandboxed_bpy = sandbox
    bpy, calls = _fake_bpy()
    return make_sandboxed_bpy(safe_module(bpy)), calls


@pytest.mark.parametrize("namespace", [
    "script", "SCRIPT", "Script", "sCrIpT",
    "extensions", "EXTENSIONS", "TEXT", "Preferences", "CONSOLE",
])
def test_denied_namespaces_are_refused_in_any_case(sandbox, namespace):
    bpy, calls = _sandboxed(sandbox)
    with pytest.raises(PermissionError, match="sandbox"):
        getattr(bpy.ops, namespace)
    assert calls == []


@pytest.mark.parametrize("namespace, operator", [
    ("WM", "open_mainfile"),
    ("Wm", "revert_mainfile"),
    ("wM", "recover_last_session"),
    ("WM", "recover_auto_save"),
    ("WM", "path_open"),
    ("WM", "url_open"),
    ("FILE", "external_operation"),
    ("WM", "context_set_value"),
    ("Wm", "properties_edit_value"),
])
def test_denied_operators_are_refused_under_any_namespace_case(sandbox, namespace, operator):
    bpy, calls = _sandboxed(sandbox)
    with pytest.raises(PermissionError, match="sandbox"):
        getattr(getattr(bpy.ops, namespace), operator)
    assert calls == []


def test_denied_kwargs_are_refused_under_any_namespace_case(sandbox):
    bpy, calls = _sandboxed(sandbox)
    with pytest.raises(PermissionError, match="sandbox"):
        bpy.ops.NODE.add_node(settings=[{"name": "x", "value": "1"}])
    assert calls == []


def test_denials_name_the_canonical_route(sandbox):
    bpy, _ = _sandboxed(sandbox)
    with pytest.raises(PermissionError, match=r"bpy\.ops\.script is not available"):
        bpy.ops.SCRIPT
    with pytest.raises(PermissionError, match=r"bpy\.ops\.wm\.open_mainfile is not available"):
        bpy.ops.WM.open_mainfile


@pytest.mark.parametrize("helper", ["_op_create_function", "_bpy_ops_submodule"])
def test_private_ops_helpers_cannot_rebuild_a_denied_operator(sandbox, helper):
    """Denying `script` alone is one hop from useless when the helper that
    builds operators by name is a plain module attribute."""
    bpy, _ = _sandboxed(sandbox)
    with pytest.raises(AttributeError, match="sandbox"):
        getattr(bpy.ops, helper)


def test_private_utils_helpers_are_refused(sandbox):
    """``bpy.utils._test_import("os", set())`` is the real ``os`` module,
    past the restricted ``__import__``; ``keyconfig_set`` execfile()s."""
    bpy, _ = _sandboxed(sandbox)
    with pytest.raises(AttributeError, match="sandbox"):
        bpy.utils._test_import
    with pytest.raises(AttributeError, match="sandbox"):
        getattr(bpy.utils, "_test" + "_import")
    with pytest.raises(AttributeError, match="sandbox"):
        bpy.utils.keyconfig_set


def test_private_names_on_other_packages_are_untouched(sandbox):
    """The private-name rule is bpy's: other packages keep their own."""
    safe_module, _ = sandbox
    import json
    assert safe_module(json)._default_encoder is json._default_encoder


def test_ordinary_operators_still_run_in_any_namespace_case(sandbox):
    bpy, calls = _sandboxed(sandbox)
    assert bpy.ops.mesh.primitive_cube_add(size=2) == {"FINISHED"}
    assert bpy.ops.MESH.primitive_cube_add(size=2) == {"FINISHED"}
    assert bpy.ops.wm.save_mainfile(filepath="/tmp/x.blend") == {"FINISHED"}
    assert bpy.ops.Object.select_all(action="SELECT") == {"FINISHED"}
    assert bpy.ops.node.add_node(type="ShaderNodeMath") == {"FINISHED"}
    assert [c[:2] for c in calls] == [
        ("mesh", "primitive_cube_add"),
        ("MESH", "primitive_cube_add"),
        ("wm", "save_mainfile"),
        ("Object", "select_all"),
        ("node", "add_node"),
    ]
    assert bpy.utils.user_resource("CONFIG") == "/tmp"
