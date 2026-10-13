# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral coverage; native geometry coverage lives in tests/qa/bmesh_guard*."""
import ast
import sys
import importlib
from pathlib import Path
from types import SimpleNamespace, ModuleType

import pytest

# Load this self-contained core without starting the connection/auth package.
_pkg = ModuleType("_mesh_guard_tests")
_pkg.__path__ = [str(Path(__file__).parents[1] / "src/scripts/mixar/modules/space_mixie_chat/core")]
sys.modules[_pkg.__name__] = _pkg
_guard = importlib.import_module("_mesh_guard_tests.sandbox_mesh")
guard_from_mesh = _guard.guard_from_mesh
guard_mesh_conversions = _guard.guard_mesh_conversions
get_safe_builtins = importlib.import_module("_mesh_guard_tests.sandbox_builtins").get_safe_builtins


@pytest.fixture
def native(monkeypatch):
    probes = []

    class Mesh:
        name = "River"
        invalid = False
        fail_validation = False

        def copy(self):
            probe = Mesh()
            probe.invalid = self.invalid
            probe.fail_validation = self.fail_validation
            probes.append(probe)
            return probe

        def validate(self, **kwargs):
            assert kwargs == {"verbose": False, "clean_customdata": False}
            assert self in probes, "never validate the original"
            if self.fail_validation:
                raise RuntimeError("validation failed")
            return self.invalid

    class BMesh:
        def __init__(self):
            self.calls = []

        def from_mesh(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return "native result"

    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(
        types=SimpleNamespace(Mesh=Mesh),
        data=SimpleNamespace(meshes=SimpleNamespace(remove=probes.remove)),
    ))
    monkeypatch.setitem(sys.modules, "bmesh", SimpleNamespace(types=SimpleNamespace(BMesh=BMesh)))
    return Mesh(), BMesh(), BMesh, probes


@pytest.mark.parametrize("expression", [
    "bm.from_mesh(mesh, vertex_normals=False)",
    "load = bm.from_mesh; load(mesh, vertex_normals=False)",
    "getattr(bm, 'from_' + 'mesh')(mesh, vertex_normals=False)",
    "BMesh.from_mesh(bm, mesh=mesh, vertex_normals=False)",
])
@pytest.mark.parametrize("invalid", [True, False])
def test_conversion_guard_covers_aliases_and_preserves_arguments(native, expression, invalid):
    mesh, bm, cls, probes = native
    mesh.invalid = invalid
    namespace = dict(mesh=mesh, bm=bm, BMesh=cls,
                     _mixar_guard_from_mesh=guard_from_mesh,
                     __builtins__=get_safe_builtins())
    code = compile(guard_mesh_conversions(ast.parse(expression)), "<test>", "exec")
    if invalid:
        with pytest.raises(ValueError, match="Invalid mesh topology.*River"):
            exec(code, namespace)
        assert not bm.calls
    else:
        exec(code, namespace)
        assert len(bm.calls) == 1
        args, kwargs = bm.calls[0]
        assert (args[0] if args else kwargs["mesh"]) is mesh
        assert kwargs["vertex_normals"] is False
    assert mesh.invalid is invalid
    assert not probes


def test_validation_error_also_cleans_temporary_mesh(native):
    mesh, bm, _, probes = native
    mesh.fail_validation = True
    with pytest.raises(RuntimeError, match="validation failed"):
        guard_from_mesh(bm.from_mesh)(mesh)
    assert not bm.calls and not probes


def test_rechecks_after_mesh_mutation(native):
    mesh, bm, _, probes = native
    convert = guard_from_mesh(bm.from_mesh)
    assert convert(mesh) == "native result"
    mesh.invalid = True
    with pytest.raises(ValueError):
        convert(mesh)
    assert len(bm.calls) == 1 and not probes


def test_unrelated_methods_and_getattr_defaults_are_unchanged(native):
    fn = lambda value: value
    assert guard_from_mesh(fn) is fn
    obj = SimpleNamespace(from_mesh=fn)
    getter = get_safe_builtins()["getattr"]
    assert getter(obj, "from_mesh")(5) == 5
    assert getter(obj, "missing", 8) == 8
    assert getter(object(), "from_mesh", None) is None
