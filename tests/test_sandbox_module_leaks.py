# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Injected sandbox modules must not hand out modules from other packages.

Denying ``import os`` is not enough. An allowed module can bind another module
as an ordinary attribute, and a plain attribute name never trips the AST dunder
guard, so these all reached the real ``os`` -- and through it ``builtins.exec``
-- with no dunder access at all::

    random._os.system(...)                 # _os IS the os module
    fractions.sys.modules['os']
    statistics.sys.modules['os']
    datetime.sys.modules['os']
    collections._sys.modules['os']
    re.enum.sys.modules['os']
    json.codecs.sys.modules['os']
    numpy.ctypeslib.ctypes.CDLL

``safe_module`` allows a module attribute only when it belongs to the same
top-level package, so same-package submodules (``collections.abc``,
``numpy.linalg``) keep working while every cross-package hop is refused.
"""

import ast
import importlib
import importlib.util
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_CORE = _ROOT / "src/scripts/mixar/modules/space_mixie_chat/core"


def _load_sandbox_modules():
    spec = importlib.util.spec_from_file_location(
        "sandbox_modules_under_test", _CORE / "sandbox_modules.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safe_module = _load_sandbox_modules().safe_module

# (module, attribute) pairs that were confirmed-working escape hops.
ESCAPE_HOPS = [
    ("random", "_os"),
    ("fractions", "sys"),
    ("statistics", "sys"),
    ("datetime", "sys"),
    ("collections", "_sys"),
    ("re", "enum"),
    ("re", "functools"),
    ("re", "copyreg"),
    ("json", "codecs"),
    ("textwrap", "re"),
    ("hashlib", "_hashlib"),
]

# Same-package submodules that scripts legitimately use.
SAME_PACKAGE = [
    ("collections", "abc"),
    ("numpy", "linalg"),
    ("numpy", "random"),
    ("numpy", "fft"),
]


@pytest.mark.parametrize("mod_name,attr", ESCAPE_HOPS)
def test_cross_package_module_attributes_are_refused(mod_name, attr):
    real = importlib.import_module(mod_name)
    if not isinstance(getattr(real, attr, None), types.ModuleType):
        pytest.skip(f"{mod_name}.{attr} is not a module on this interpreter")
    with pytest.raises(AttributeError) as excinfo:
        getattr(safe_module(real), attr)
    assert "sandbox" in str(excinfo.value)


@pytest.mark.parametrize("mod_name,attr", SAME_PACKAGE)
def test_same_package_submodules_still_resolve(mod_name, attr):
    real = pytest.importorskip(mod_name)
    if not isinstance(getattr(real, attr, None), types.ModuleType):
        pytest.skip(f"{mod_name}.{attr} is not a module on this interpreter")
    assert getattr(safe_module(real), attr) is not None


def test_a_wrapped_submodule_is_itself_wrapped():
    """numpy.linalg is allowed, but must not become an unguarded door."""
    numpy = pytest.importorskip("numpy")
    linalg = getattr(safe_module(numpy), "linalg")
    for attr in dir(numpy.linalg):
        value = getattr(numpy.linalg, attr, None)
        if isinstance(value, types.ModuleType) and not value.__name__.startswith("numpy"):
            with pytest.raises(AttributeError):
                getattr(linalg, attr)


def test_the_proxy_exposes_no_foreign_module_at_all():
    """Generic guard: the next stdlib release can add a new re-export."""
    leaked = []
    for mod_name in _injected_module_names():
        try:
            real = importlib.import_module(mod_name)
        except ImportError:
            continue
        proxy = safe_module(real)
        root = mod_name.partition(".")[0]
        try:
            attrs = dir(real)
        except Exception:  # pragma: no cover - defensive
            continue
        for attr in attrs:
            # numpy resolves several attributes through a lazy module-level
            # __getattr__, which can recurse under the suite's mocked import
            # machinery. A probe that cannot even be read is not a leak.
            try:
                value = getattr(real, attr, None)
            except Exception:
                continue
            if not isinstance(value, types.ModuleType):
                continue
            name = getattr(value, "__name__", "")
            if name == root or name.startswith(root + "."):
                continue
            try:
                getattr(proxy, attr)
            except AttributeError:
                continue
            leaked.append(f"{mod_name}.{attr} -> {name}")
    assert not leaked, "sandbox modules re-export foreign modules: " + ", ".join(leaked)


def test_the_proxy_hides_the_wrapped_module_from_the_instance():
    """The module lives in a closure; there must be no attribute holding it."""
    proxy = safe_module(importlib.import_module("json"))
    assert not hasattr(proxy, "__dict__") or not vars(proxy)
    for probe in ("_mod", "_module", "_SafeModule__mod", "_SandboxedModule__mod"):
        with pytest.raises(AttributeError):
            getattr(proxy, probe)


def _injected_module_names():
    """Every real module executor.py injects, read from its source."""
    tree = ast.parse((_CORE / "executor.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "safe_module"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            names.add(node.args[0].id)
    # bpy-only modules cannot be imported outside Blender; drop them here.
    return sorted(names - {"bpy", "bmesh", "mathutils", "bpy_extras", "imbuf"})


def test_every_injected_module_is_wrapped():
    """A raw module added to the namespace later reopens the whole hole."""
    source = (_CORE / "executor.py").read_text()
    tree = ast.parse(source)
    # Only the sandbox namespace dict -- the one that binds "__builtins__".
    namespaces = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(k, ast.Constant) and k.value == "__builtins__"
            for k in node.keys if k is not None
        )
    ]
    assert namespaces, "could not find the sandbox namespace dict in executor.py"
    # `bpy` is deliberately unwrapped: it IS the capability the agent is given.
    exempt = {"bpy"}
    raw = []
    for node in namespaces:
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value in exempt:
                continue
            # A bare `"json": json` in the namespace dict is the regression.
            if isinstance(value, ast.Name) and value.id == key.value:
                raw.append(key.value)
    assert not raw, f"namespace injects unwrapped modules: {raw}"


def test_injected_module_list_is_not_empty():
    """Guards the AST scrape above from silently matching nothing."""
    assert len(_injected_module_names()) >= 10
