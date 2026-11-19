# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression tests for splat worlds in the outliner (``splat_lifecycle``).

Splats are Blender's built-in Gaussian splat objects, so hiding and deleting
are plain Blender. What is pinned here is what Mixar still adds: imported
worlds are stamped, a world whose splat was deleted loses its hidden
leftovers (and only those), the scan stays off the per-edit path, and opening
a file schedules the KIRI-era conversion.
"""

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MOD_PATH = (
    _REPO_ROOT / "src/scripts/mixar/modules/moodboard/core/splat_lifecycle.py"
)


# --------------------------------------------------------------------------- #
# Blender stubs
# --------------------------------------------------------------------------- #

class _IdEq:
    """Blender IDs compare by identity; these fakes are dicts, which do not."""

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__


class _Object(_IdEq, dict):
    def __init__(self, name, otype="MESH", splat=False, **props):
        super().__init__(props)
        self.name = name
        self.type = otype
        self.splat = splat


class _Collection(_IdEq, dict):
    def __init__(self, name, objects=(), **props):
        super().__init__(props)
        self.name = name
        self.objects = list(objects)
        self.children = []


class _ObjectList(list):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def remove(self, obj, do_unlink=False):
        list.remove(self, obj)
        for collection in self._data.collections:
            if obj in collection.objects:
                collection.objects.remove(obj)


class _CollectionList(list):
    def remove(self, collection):
        list.remove(self, collection)


class _Data:
    def __init__(self):
        self.collections = _CollectionList()
        self.objects = _ObjectList(self)


class _Timers:
    def __init__(self):
        self.registered = {}

    def is_registered(self, fn):
        return fn in self.registered

    def register(self, fn, first_interval=0.0, **_kwargs):
        self.registered[fn] = first_interval

    def unregister(self, fn):
        self.registered.pop(fn)


@pytest.fixture
def lifecycle(monkeypatch):
    """Load splat_lifecycle against stubbed bpy + splat_native + splat_legacy."""
    timers = _Timers()
    handlers = types.ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    app = types.ModuleType("bpy.app")
    app.handlers = handlers
    app.timers = timers
    bpy = types.ModuleType("bpy")
    bpy.app = app
    bpy.data = _Data()

    logging_stub = types.ModuleType("mixar.config.logging_config")
    logging_stub.get_logger = lambda _name: MagicMock()

    native = types.ModuleType("mixar.modules.moodboard.core.splat_native")
    native.is_splat = lambda obj: obj.splat

    legacy = types.ModuleType("mixar.modules.moodboard.core.splat_legacy")
    legacy.convert_kiri_splats = MagicMock(return_value=[])

    for name, module in (
        ("bpy", bpy),
        ("bpy.app", app),
        ("bpy.app.handlers", handlers),
        ("mixar.config.logging_config", logging_stub),
        ("mixar.modules.moodboard.core.splat_native", native),
        ("mixar.modules.moodboard.core.splat_legacy", legacy),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("test_splat_lifecycle_mod", _MOD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return types.SimpleNamespace(mod=module, bpy=bpy, timers=timers, legacy=legacy)


def _world(data, stem, *, with_collider=True, flagged=True):
    """An imported splat world: the splat (+ its hidden collider)."""
    splat = _Object(f"{stem}_Splat", otype="POINTCLOUD", splat=True, wl_role="splat")
    objects = [splat]
    if with_collider:
        objects.append(_Object(f"{stem}_Collider", wl_role="collider"))
    props = {"mixar_splat_world": True} if flagged else {}
    collection = _Collection(f"WorldLabs_{stem}", objects, **props)
    data.collections.append(collection)
    data.objects.extend(objects)
    return types.SimpleNamespace(collection=collection, splat=splat, objects=objects)


def _delete(data, obj):
    data.objects.remove(obj, do_unlink=True)


# --------------------------------------------------------------------------- #
# Import-time stamping
# --------------------------------------------------------------------------- #

def test_finalize_stamps_splats_and_flags_the_world(lifecycle):
    splat = _Object("Room", otype="POINTCLOUD", splat=True)
    collection = _Collection("Splat_Room", [splat])
    lifecycle.mod.finalize_splat_handles(collection, [splat])
    assert splat["wl_role"] == "splat"
    assert collection["mixar_splat_world"] is True


def test_finalize_never_flags_a_world_without_a_splat(lifecycle):
    mesh = _Object("NotASplat")
    collection = _Collection("Splat_Mesh", [mesh])
    lifecycle.mod.finalize_splat_handles(collection, [mesh])
    assert "mixar_splat_world" not in collection
    assert "wl_role" not in mesh


# --------------------------------------------------------------------------- #
# Deleting a world
# --------------------------------------------------------------------------- #

def test_deleting_a_splat_purges_its_world_and_keeps_the_other(lifecycle):
    data = lifecycle.bpy.data
    room, yard = _world(data, "Room"), _world(data, "Yard")
    lifecycle.mod.note_splats_imported()

    _delete(data, room.splat)
    lifecycle.mod._check_splats()

    assert room.collection not in data.collections
    assert all(obj not in data.objects for obj in room.objects)
    assert yard.collection in data.collections
    assert all(obj in data.objects for obj in yard.objects)


def test_purge_leaves_user_objects_and_unflagged_collections_alone(lifecycle):
    data = lifecycle.bpy.data
    room = _world(data, "Room")
    user_obj = _Object("MyChair")
    room.collection.objects.append(user_obj)
    data.objects.append(user_obj)
    other = _world(data, "Other", flagged=False)
    lifecycle.mod.note_splats_imported()

    _delete(data, room.splat)
    _delete(data, other.splat)
    lifecycle.mod._check_splats()

    assert room.collection in data.collections
    assert room.collection.objects == [user_obj]
    assert other.collection in data.collections
    assert other.objects[1] in data.objects  # unflagged collider survives


def test_adding_a_world_never_purges(lifecycle):
    data = lifecycle.bpy.data
    room = _world(data, "Room")
    lifecycle.mod.note_splats_imported()
    _world(data, "New")
    lifecycle.mod._check_splats()
    assert room.collection in data.collections
    assert len(data.objects) == 4


def test_renamed_splat_does_not_read_as_deleted(lifecycle):
    data = lifecycle.bpy.data
    room = _world(data, "Room")
    lifecycle.mod.note_splats_imported()
    room.splat.name = "Renamed"
    lifecycle.mod._check_splats()
    assert all(obj in data.objects for obj in room.objects)


# --------------------------------------------------------------------------- #
# Handler cost and file load
# --------------------------------------------------------------------------- #

def test_operator_burst_scans_only_after_returning_to_main_loop(lifecycle):
    mod = lifecycle.mod
    _world(lifecycle.bpy.data, "Room")
    mod.note_splats_imported()
    scan = MagicMock(wraps=mod._splat_names)
    mod._splat_names = scan
    for _ in range(1000):
        mod.on_depsgraph_update()
    scan.assert_not_called()
    assert list(lifecycle.timers.registered) == [mod._check_splats]
    mod._check_splats()
    assert scan.call_count == 1
    assert not mod._check_pending


def test_load_post_schedules_kiri_conversion_and_rebaselines(lifecycle):
    mod = lifecycle.mod
    room = _world(lifecycle.bpy.data, "Room")
    mod.on_depsgraph_update()
    mod.on_load_post()
    assert list(lifecycle.timers.registered) == [mod._convert_legacy]
    assert mod._known_splats is None

    mod._convert_legacy()
    lifecycle.legacy.convert_kiri_splats.assert_called_once_with()
    assert mod._known_splats == frozenset({room.splat.name})


def test_converted_worlds_are_flagged_for_cleanup(lifecycle):
    mod = lifecycle.mod
    splat = _Object("Old_Splat", otype="POINTCLOUD", splat=True, wl_role="splat")
    collection = _Collection("WorldLabs_Old", [splat])
    splat.users_collection = [collection]
    lifecycle.legacy.convert_kiri_splats.return_value = [splat]
    mod._convert_legacy()
    assert collection["mixar_splat_world"] is True


def test_conversion_failure_never_blocks_the_file(lifecycle):
    lifecycle.legacy.convert_kiri_splats.side_effect = RuntimeError("bad file")
    assert lifecycle.mod._convert_legacy() is None


def test_cancel_pending_clears_both_timers(lifecycle):
    mod = lifecycle.mod
    mod.on_depsgraph_update()
    mod.on_load_post()
    mod.on_depsgraph_update()
    mod.cancel_pending()
    assert not lifecycle.timers.registered
    assert not mod._check_pending


def test_detection_retries_after_timer_registration_fails(lifecycle):
    mod = lifecycle.mod
    lifecycle.timers.register = MagicMock(side_effect=[RuntimeError("restricted"), None])
    mod.on_depsgraph_update()
    assert not mod._check_pending
    mod.on_depsgraph_update()
    assert mod._check_pending
    assert lifecycle.timers.register.call_count == 2
