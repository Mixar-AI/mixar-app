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
    # Nothing is exempt any more. `bpy` used to be, on the reasoning that it IS
    # the capability the agent is given -- but Blender's own bpy/utils binds
    # `import os as _os` / `import sys as _sys`, so that exemption left the
    # whole escape class open through the one module every script has.
    exempt = set()
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


# ---------------------------------------------------------------------------
# Escapes that do NOT go through a module attribute
# ---------------------------------------------------------------------------


def test_a_same_package_bridge_out_of_python_is_refused():
    """numpy.ctypeslib is genuinely part of numpy, so the cross-package rule
    cannot see it -- but load_library() RETURNS a live ctypes.CDLL. A plain
    function return, no module hop, no dunder: verified loading libc and
    calling into it from inside the sandbox before this guard existed."""
    numpy = pytest.importorskip("numpy")
    proxy = safe_module(numpy)
    # Probed through the proxy only: numpy resolves these through a lazy
    # module-level __getattr__, and the guard refuses by NAME before the fetch
    # precisely so a denied child is never imported.
    for denied in ("ctypeslib", "f2py", "distutils"):
        with pytest.raises(AttributeError) as excinfo:
            getattr(proxy, denied)
        assert "sandbox" in str(excinfo.value)


def test_the_arithmetic_parts_of_numpy_still_resolve():
    numpy = pytest.importorskip("numpy")
    proxy = safe_module(numpy)
    assert proxy.linalg is not None
    assert proxy.random is not None
    assert float(numpy.linalg.norm(proxy.array([3.0, 4.0]))) == 5.0


def _fake_bpy():
    """A stand-in shaped like the real bpy: same-package children plus the
    foreign modules Blender's own bpy/utils/__init__.py binds as _os / _sys."""
    import os
    import sys

    bpy = types.ModuleType("bpy")
    utils = types.ModuleType("bpy.utils")
    ops = types.ModuleType("bpy.ops")
    utils._os = os                      # Blender: `import os as _os`
    utils._sys = sys                    # Blender: `import sys as _sys`
    utils.execfile = lambda path: None  # runs Python from disk
    utils.user_resource = lambda *a, **k: "/tmp"
    bpy.utils = utils
    bpy.ops = ops
    bpy.data = object()
    return bpy


def test_bpy_cannot_hand_out_the_os_module_through_utils():
    """The one module every agent script receives. Leaving it unwrapped meant
    bpy.utils._os.system(...) and bpy.utils._sys.modules['builtins'].exec(...)
    reached the real os/sys with no dunder involved."""
    proxy = safe_module(_fake_bpy())
    utils = proxy.utils
    for leaked in ("_os", "_sys"):
        with pytest.raises(AttributeError) as excinfo:
            getattr(utils, leaked)
        assert "sandbox" in str(excinfo.value)


def test_bpy_utils_cannot_run_python_from_disk():
    """Same-package, so the module rule does not apply -- but execfile and its
    siblings are arbitrary-code loaders."""
    utils = safe_module(_fake_bpy()).utils
    with pytest.raises(AttributeError) as excinfo:
        utils.execfile
    assert "sandbox" in str(excinfo.value)


def test_wrapping_bpy_keeps_the_capability_it_exists_for():
    """Every same-package child must still resolve, or every agent script
    breaks: this guard is only worth having if bpy still works."""
    proxy = safe_module(_fake_bpy())
    assert proxy.ops is not None
    assert proxy.data is not None
    assert proxy.utils.user_resource() == "/tmp"
