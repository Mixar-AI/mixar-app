# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Wiring tests for the local splat import (``core/splat_import.py``).

Loaded by file path with the ``mixar.*`` dependencies stubbed (the module
itself only orchestrates), pinning the contracts that matter:

* ``.spz`` goes through the shared native import (``splat_native.import_splat_spz``,
  Blender's ``wm.spz_import``) and is rotated per source: none for the spec
  frame, the World Labs rotation (180 deg X) for Marble;
* a plain ``.ply`` goes to the PLY splat import with the raw-PLY rotation;
* the splat is oriented, then recentred, then stamped and framed;
* a failing import leaves no empty collection behind;
* a PLY that imports as anything but a built-in splat is removed and refused;
* unsupported extensions / missing files refuse loudly;
* ``import_splat_spz`` itself refuses a build without the SPZ importer.
"""

import importlib.util
import os
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CORE = _REPO_ROOT / "src/scripts/mixar/modules/moodboard/core"
_MOD_PATH = _CORE / "splat_import.py"
_WORLD_LABS_ROT = (180.0, 0.0, 0.0)


class _Recorder:
    """Records the order importer helpers were invoked in."""

    def __init__(self, splat=True):
        self.calls = []
        self.args = {}
        self.temp_ply_seen = ""
        self.spz_seen = ""
        self.spz_error = None
        self.splat = splat

    def make(self, name, ret=None):
        def _fn(*args, **kwargs):
            self.calls.append(name)
            self.args[name] = args
            if name == "_import_tracked":
                # args[0] is the lambda wrapping _import_splat_ply
                args[0]()
                obj = MagicMock(name="splat_obj")
                obj.is_splat = self.splat
                return [obj]
            return ret if ret is not None else []
        return _fn


@pytest.fixture
def stub_env():
    """Keeps sys.modules overrides installed for the whole test.

    The module resolves its imports at load and call time, so the stubs must
    outlive module load and stay in place during the call.
    """
    saved = {}

    def install(overrides):
        for k, v in overrides.items():
            saved.setdefault(k, sys.modules.get(k))
            sys.modules[k] = v

    yield install
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _load(recorder, install):
    """Load splat_import.py with stubbed dependencies; returns the module."""
    importer_stub = types.ModuleType(
        "mixar.modules.moodboard.core.world_labs_importer"
    )
    for name in (
        "_ensure_object_mode", "_frame_objects", "_move_to_collection",
        "_orient_splats",
    ):
        setattr(importer_stub, name, recorder.make(name))
    importer_stub._recenter_world_to_ground = recorder.make("_recenter")
    importer_stub.RAW_PLY_ROT_EULER_DEG = (-90.0, 0.0, 0.0)
    importer_stub.WORLD_LABS_SPZ_ROT_EULER_DEG = _WORLD_LABS_ROT

    def _import_splat_ply(ply_path):
        recorder.calls.append("_import_splat_ply")
        recorder.temp_ply_seen = ply_path
    importer_stub._import_splat_ply = _import_splat_ply
    importer_stub._import_tracked = recorder.make("_import_tracked")

    native_stub = types.ModuleType("mixar.modules.moodboard.core.splat_native")
    native_stub.is_splat = lambda obj: obj.is_splat

    def import_splat_spz(path):
        recorder.calls.append("import_splat_spz")
        recorder.spz_seen = path
        if recorder.spz_error is not None:
            raise recorder.spz_error
    native_stub.import_splat_spz = import_splat_spz

    lifecycle_stub = types.ModuleType("mixar.modules.moodboard.core.splat_lifecycle")
    lifecycle_stub.finalize_splat_handles = recorder.make("_finalize")
    lifecycle_stub.note_splats_imported = recorder.make("_note")

    logging_stub = types.ModuleType("mixar.config.logging_config")
    logging_stub.get_logger = lambda name: MagicMock()

    install({
        "mixar.modules.moodboard.core.world_labs_importer": importer_stub,
        "mixar.modules.moodboard.core.splat_native": native_stub,
        "mixar.modules.moodboard.core.splat_lifecycle": lifecycle_stub,
        "mixar.config.logging_config": logging_stub,
    })
    spec = importlib.util.spec_from_file_location("splat_import", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Collection creation touches bpy (stubbed by root conftest).
    mod._new_splat_collection = lambda name: MagicMock(name="collection")
    mod.bpy = MagicMock()
    return mod


def test_spz_uses_native_importer(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    spz = tmp_path / "room.spz"
    spz.write_bytes(b"SPZDATA")

    names = mod.import_splat_file(str(spz))

    assert rec.spz_seen == str(spz)
    assert "_import_splat_ply" not in rec.calls
    assert names  # imported object names returned


@pytest.mark.parametrize("source, euler", [
    ("STANDARD", (0.0, 0.0, 0.0)),
    ("WORLD_LABS", _WORLD_LABS_ROT),
])
def test_spz_rotation_follows_source(tmp_path, stub_env, source, euler):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    spz = tmp_path / "room.spz"
    spz.write_bytes(b"SPZ")

    mod.import_splat_file(str(spz), source=source)
    assert rec.args["_orient_splats"][1] == euler


def test_unknown_source_refused(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    spz = tmp_path / "room.spz"
    spz.write_bytes(b"SPZ")

    with pytest.raises(ValueError):
        mod.import_splat_file(str(spz), source="MARBLE")
    assert not rec.calls


def test_ply_goes_to_ply_import_with_raw_rotation(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\n")

    mod.import_splat_file(str(ply), source="WORLD_LABS")
    assert rec.temp_ply_seen == str(ply)
    assert "import_splat_spz" not in rec.calls
    assert rec.args["_orient_splats"][1] == (-90.0, 0.0, 0.0)


def test_splat_oriented_then_recentred_then_stamped(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\n")

    mod.import_splat_file(str(ply), recenter=True)

    steps = ("_orient_splats", "_recenter", "_finalize", "_frame_objects", "_note")
    assert [c for c in rec.calls if c in steps] == list(steps)


def test_non_splat_ply_is_removed_and_refused(tmp_path, stub_env):
    rec = _Recorder(splat=False)
    mod = _load(rec, stub_env)
    ply = tmp_path / "mesh.ply"
    ply.write_bytes(b"ply\n")
    removed = []
    mod.bpy = MagicMock()
    mod.bpy.data.objects.remove.side_effect = lambda obj, **_kw: removed.append(obj)

    with pytest.raises(ValueError):
        mod.import_splat_file(str(ply))
    assert len(removed) == 1
    assert mod.bpy.data.collections.remove.called
    assert "_finalize" not in rec.calls


def test_failed_import_removes_collection(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)
    spz = tmp_path / "bad.spz"
    spz.write_bytes(b"SPZ")
    rec.spz_error = RuntimeError("malformed")

    with pytest.raises(RuntimeError):
        mod.import_splat_file(str(spz))
    assert mod.bpy.data.collections.remove.called
    assert "_finalize" not in rec.calls


def test_rejects_unknown_extension_and_missing_file(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, stub_env)

    exr = tmp_path / "not_a_splat.exr"
    exr.write_bytes(b"x")
    with pytest.raises(ValueError):
        mod.import_splat_file(str(exr))

    with pytest.raises(ValueError):
        mod.import_splat_file(str(tmp_path / "missing.spz"))


def _load_native(install, io_spz):
    """Load splat_native.py with a stub bpy and i18n."""
    bpy_stub = MagicMock()
    bpy_stub.app.build_options.io_spz = io_spz
    i18n_stub = types.ModuleType("mixar.modules.common.i18n")
    i18n_stub.rpt_ = lambda text: text
    install({"bpy": bpy_stub, "mixar.modules.common.i18n": i18n_stub})
    spec = importlib.util.spec_from_file_location("splat_native", _CORE / "splat_native.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, bpy_stub


def test_native_spz_import_calls_blender_importer(stub_env):
    mod, bpy_stub = _load_native(stub_env, io_spz=True)
    mod.import_splat_spz("/tmp/world.spz")
    bpy_stub.ops.wm.spz_import.assert_called_once_with(filepath="/tmp/world.spz")


def test_native_spz_import_refused_without_io_spz(stub_env):
    mod, bpy_stub = _load_native(stub_env, io_spz=False)
    with pytest.raises(ValueError):
        mod.import_splat_spz("/tmp/world.spz")
    assert not bpy_stub.ops.wm.spz_import.called
