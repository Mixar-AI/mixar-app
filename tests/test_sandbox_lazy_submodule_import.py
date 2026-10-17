# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`from <injected package> import <submodule>` loads a lazy submodule.

Agent scripts wrote `from bpy_extras import anim_utils` (the documented
Blender idiom) and got "cannot import name 'anim_utils'": the restricted
import handed back the injected bpy_extras proxy without loading the
submodule the real import system would have loaded from the fromlist.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

_CORE_ROOT = (Path(__file__).parents[1] / "src" / "scripts" / "mixar" / "modules"
              / "space_mixie_chat" / "core")


def _load_core(monkeypatch, leaf):
    roots = {
        "mixar": _CORE_ROOT.parents[2],
        "mixar.modules": _CORE_ROOT.parents[1],
        "mixar.modules.space_mixie_chat": _CORE_ROOT.parent,
        "mixar.modules.space_mixie_chat.core": _CORE_ROOT,
    }
    for name, path in roots.items():
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    for dep in ("sandbox_denylist", "sandbox_modules", leaf):
        name = f"mixar.modules.space_mixie_chat.core.{dep}"
        spec = importlib.util.spec_from_file_location(name, _CORE_ROOT / f"{dep}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def lazy_pkg(tmp_path, monkeypatch):
    pkg = tmp_path / "qa_lazy_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "helpers.py").write_text("VALUE = 42\n")
    (pkg / "secret.py").write_text("VALUE = 'escape'\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("qa_lazy_pkg", "qa_lazy_pkg.helpers", "qa_lazy_pkg.secret"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import qa_lazy_pkg
    return qa_lazy_pkg


@pytest.fixture
def run(monkeypatch, lazy_pkg):
    sandbox_import = _load_core(monkeypatch, "sandbox_import")
    sandbox_modules = sys.modules["mixar.modules.space_mixie_chat.core.sandbox_modules"]
    monkeypatch.setattr(sandbox_import, "_PASS_THROUGH_PACKAGES",
                        sandbox_import._PASS_THROUGH_PACKAGES + ("qa_lazy_pkg",))
    monkeypatch.setattr(sandbox_import, "is_denied_module",
                        lambda name: name == "qa_lazy_pkg.secret")
    namespace = {"qa_lazy_pkg": sandbox_modules.safe_module(lazy_pkg)}
    restricted = sandbox_import.make_restricted_import(namespace)

    def _run(code):
        scope = {"__builtins__": {"__import__": restricted}}
        exec(code, scope)  # noqa: S102 - the restricted import under test
        return scope
    return _run


def test_from_package_import_loads_a_lazy_submodule(run):
    scope = run("from qa_lazy_pkg import helpers\nresult = helpers.VALUE")
    assert scope["result"] == 42


def test_a_denied_submodule_is_still_not_loaded(run):
    with pytest.raises(ImportError):
        run("from qa_lazy_pkg import secret")
    assert "qa_lazy_pkg.secret" not in sys.modules


def test_a_name_that_is_no_submodule_still_fails_as_a_missing_name(run):
    with pytest.raises(ImportError, match="nothing_here"):
        run("from qa_lazy_pkg import nothing_here")
