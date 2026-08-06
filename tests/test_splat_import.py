# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Wiring tests for the local splat import (``core/splat_import.py``).

Loaded by file path with the ``mixar.*`` dependencies stubbed (the module
itself only orchestrates), pinning the contracts that matter:

* ``.spz`` goes through ``spz_to_ply`` into a temp PLY that is ALWAYS
  cleaned up (success and failure);
* a plain ``.ply`` is passed straight through (no conversion, no temp);
* the KIRI render proxy is built AFTER orientation + recentring (the
  proxy-in-final-pose rule from the World Labs importer);
* unsupported extensions / missing files refuse loudly.
"""

import importlib.util
import os
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MOD_PATH = (
    _REPO_ROOT / "src/scripts/mixar/modules/moodboard/core/splat_import.py"
)


class _Recorder:
    """Records the order importer helpers were invoked in."""

    def __init__(self):
        self.calls = []
        self.temp_ply_seen = ""

    def make(self, name, ret=None):
        def _fn(*args, **kwargs):
            self.calls.append(name)
            if name == "_import_tracked":
                # args[0] is the lambda wrapping _import_splat_ply
                args[0]()
                return [MagicMock(name="splat_obj")]
            return ret if ret is not None else []
        return _fn


@pytest.fixture
def stub_env():
    """Keeps sys.modules overrides installed for the whole test.

    ``import_splat_file`` imports ``spz_to_ply`` lazily at call time, so the
    stubs must outlive module load and stay in place during the call.
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


def _load(recorder, spz_to_ply, install):
    """Load splat_import.py with stubbed dependencies; returns the module."""
    importer_stub = types.ModuleType(
        "mixar.modules.moodboard.core.world_labs_importer"
    )
    for name in (
        "_ensure_object_mode", "_finalize_visibility", "_frame_objects",
        "_move_to_collection", "_orient_splats",
    ):
        setattr(importer_stub, name, recorder.make(name))
    importer_stub._recenter_world_to_ground = recorder.make("_recenter")
    importer_stub._enable_splat_render = recorder.make("_proxy", ret=[])

    def _import_splat_ply(ply_path):
        recorder.calls.append("_import_splat_ply")
        recorder.temp_ply_seen = ply_path
    importer_stub._import_splat_ply = _import_splat_ply
    importer_stub._import_tracked = recorder.make("_import_tracked")

    spz_stub = types.ModuleType("mixar.modules.moodboard.core.world_labs_spz")
    spz_stub.spz_to_ply = spz_to_ply

    logging_stub = types.ModuleType("mixar.config.logging_config")
    logging_stub.get_logger = lambda name: MagicMock()

    install({
        "mixar.modules.moodboard.core.world_labs_importer": importer_stub,
        "mixar.modules.moodboard.core.world_labs_spz": spz_stub,
        "mixar.config.logging_config": logging_stub,
    })
    spec = importlib.util.spec_from_file_location("splat_import", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Collection creation touches bpy (stubbed by root conftest).
    mod._new_splat_collection = lambda name: MagicMock(name="collection")
    return mod


def test_spz_converts_via_temp_ply_and_cleans_up(tmp_path, stub_env):
    rec = _Recorder()
    converted = {}

    def fake_spz_to_ply(data):
        converted["input"] = data
        return b"PLYBYTES"

    mod = _load(rec, fake_spz_to_ply, stub_env)
    spz = tmp_path / "room.spz"
    spz.write_bytes(b"SPZDATA")

    names = mod.import_splat_file(str(spz))

    assert converted["input"] == b"SPZDATA"
    assert rec.temp_ply_seen.endswith(".ply")
    assert rec.temp_ply_seen != str(spz)
    assert not os.path.exists(rec.temp_ply_seen), "temp PLY must be removed"
    assert names  # imported object names returned


def test_ply_passes_through_without_conversion(tmp_path, stub_env):
    rec = _Recorder()

    def fail_spz_to_ply(data):  # pragma: no cover - must not be called
        raise AssertionError("spz_to_ply must not run for .ply input")

    mod = _load(rec, fail_spz_to_ply, stub_env)
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\n")

    mod.import_splat_file(str(ply))
    assert rec.temp_ply_seen == str(ply)


def test_proxy_built_after_orient_and_recenter(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, lambda data: b"PLY", stub_env)
    ply = tmp_path / "scene.ply"
    ply.write_bytes(b"ply\n")

    mod.import_splat_file(str(ply), recenter=True)

    order = [c for c in rec.calls if c in ("_orient_splats", "_recenter", "_proxy")]
    assert order == ["_orient_splats", "_recenter", "_proxy"]


def test_temp_cleaned_up_when_import_fails(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, lambda data: b"PLY", stub_env)
    spz = tmp_path / "bad.spz"
    spz.write_bytes(b"SPZ")

    seen = {}

    def exploding_tracked(fn):
        fn()
        seen["temp"] = rec.temp_ply_seen
        raise RuntimeError("boom")

    # Patch on the loaded module (it imported the name at load time).
    mod._import_tracked = exploding_tracked

    with pytest.raises(RuntimeError):
        mod.import_splat_file(str(spz))
    assert seen["temp"] and not os.path.exists(seen["temp"])


def test_rejects_unknown_extension_and_missing_file(tmp_path, stub_env):
    rec = _Recorder()
    mod = _load(rec, lambda data: b"PLY", stub_env)

    exr = tmp_path / "not_a_splat.exr"
    exr.write_bytes(b"x")
    with pytest.raises(ValueError):
        mod.import_splat_file(str(exr))

    with pytest.raises(ValueError):
        mod.import_splat_file(str(tmp_path / "missing.spz"))
