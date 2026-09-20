# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression tests for hiding/deleting splat worlds from the outliner.

Two halves, matching where the fix lives:

* ``splat_lifecycle`` — reconciling KIRI's process-global runtime with outliner
  deletions, and mirroring viewport visibility onto the render flag;
* the vendored KIRI patch — the metadata texture must carry each proxy's real
  visibility, because ``assets/vert.glsl`` culls on it.
"""

import importlib.util
import pathlib
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MOD_PATH = (
    _REPO_ROOT / "src/scripts/mixar/modules/moodboard/core/splat_lifecycle.py"
)
_KIRI_PATH = _REPO_ROOT / "src/scripts/addons_core/kiri_3dgs_render/__init__.py"
_VERT_GLSL = _REPO_ROOT / "src/scripts/addons_core/kiri_3dgs_render/assets/vert.glsl"


# --------------------------------------------------------------------------- #
# Blender stubs
# --------------------------------------------------------------------------- #

class _IdEq:
    """Blender IDs compare by identity; these fakes are dicts, which do not."""

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__


class _Object(_IdEq, dict):
    def __init__(self, name, otype="EMPTY", visible=True, **props):
        super().__init__(props)
        self.name = name
        self.type = otype
        self.hide_viewport = False
        self.hide_render = False
        self._visible = visible

    def visible_get(self):
        return self._visible


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
    """Load splat_lifecycle against stubbed bpy + splat_render_camera."""
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

    calls = []
    kiri = types.ModuleType("kiri_3dgs_render")
    kiri.sna_clean_up_scene_5F1F1 = lambda remove: calls.append(("cleanup", remove))
    kiri.sna_texture_creation_FD1B2 = lambda: calls.append(("texture",))

    src = types.ModuleType("mixar.modules.moodboard.core.splat_render_camera")
    src._KIRI_CLEANUP_FN = "sna_clean_up_scene_5F1F1"
    src._KIRI_TEXTURE_FN = "sna_texture_creation_FD1B2"
    src._ready_kiri_module = lambda: kiri
    src._saved_splat_proxies = lambda: [
        obj for obj in bpy.data.objects
        if obj.get("is_gaussian_splat") and int(obj.get("gaussian_count", 0) or 0) > 0
    ]

    core_pkg = types.ModuleType("mixar.modules.moodboard.core")
    core_pkg.splat_render_camera = src

    for name, module in (
        ("bpy", bpy),
        ("bpy.app", app),
        ("bpy.app.handlers", handlers),
        ("mixar.config.logging_config", logging_stub),
        ("mixar.modules.moodboard.core", core_pkg),
        ("mixar.modules.moodboard.core.splat_render_camera", src),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("test_splat_lifecycle_mod", _MOD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return types.SimpleNamespace(mod=module, bpy=bpy, timers=timers, calls=calls)


def _world(data, stem, *, with_proxy=True, with_collider=True):
    """Build an imported splat world: proxy + hidden source mesh (+ collider)."""
    objects = []
    mesh = _Object(
        stem, otype="MESH", visible=False,
        gaussian_source_uuid=f"uuid-{stem}", wl_role="splat",
    )
    objects.append(mesh)
    proxy = None
    if with_proxy:
        proxy = _Object(
            f"{stem}Splat_Proxy",
            is_gaussian_splat=True,
            gaussian_count=10,
            source_mesh_uuid=f"uuid-{stem}",
            wl_role="proxy",
        )
        objects.append(proxy)
    if with_collider:
        objects.append(_Object(f"{stem}_collider", otype="MESH", wl_role="collider"))
    collection = _Collection(f"WorldLabs_{stem}", objects, mixar_splat_world=True)
    data.collections.append(collection)
    data.objects.extend(objects)
    return types.SimpleNamespace(
        collection=collection, mesh=mesh, proxy=proxy, objects=objects,
    )


# --------------------------------------------------------------------------- #
# Deleting a world
# --------------------------------------------------------------------------- #

def test_deleting_one_world_rebuilds_textures_and_keeps_the_other(lifecycle):
    mod, bpy, calls = lifecycle.mod, lifecycle.bpy, lifecycle.calls
    kept = _world(bpy.data, "Kept")
    doomed = _world(bpy.data, "Doomed")
    bpy.gaussian_object_cache = {
        kept.proxy.name: {"object": kept.proxy},
        doomed.proxy.name: {"object": doomed.proxy},
    }
    mod.note_splats_imported()

    bpy.data.objects.remove(doomed.proxy)  # user deletes the proxy in the outliner
    mod.on_depsgraph_update()
    assert lifecycle.timers.is_registered(mod.reconcile_splats)
    mod.reconcile_splats()

    # The surviving world keeps rendering: textures are rebuilt, not left in the
    # "Global textures missing - run script_3 first" state.
    assert ("texture",) in calls
    assert ("cleanup", False) not in calls
    assert list(bpy.gaussian_object_cache) == [kept.proxy.name]


def test_deleting_a_world_purges_its_leftovers(lifecycle):
    mod, bpy = lifecycle.mod, lifecycle.bpy
    kept = _world(bpy.data, "Kept")
    doomed = _world(bpy.data, "Doomed")
    bpy.gaussian_object_cache = {
        kept.proxy.name: {"object": kept.proxy},
        doomed.proxy.name: {"object": doomed.proxy},
    }
    mod.note_splats_imported()

    bpy.data.objects.remove(doomed.proxy)
    mod.reconcile_splats()

    # The hidden point-cloud mesh still renders splat quads through its geometry
    # nodes at F12, so it must not survive its proxy — nor must the collider.
    names = [obj.name for obj in bpy.data.objects]
    assert doomed.mesh.name not in names
    assert f"{doomed.mesh.name}_collider" not in names
    assert doomed.collection not in bpy.data.collections
    # ...and the untouched world is entirely intact.
    assert kept.mesh.name in names
    assert kept.collection in bpy.data.collections


def test_purge_leaves_user_objects_and_unflagged_collections_alone(lifecycle):
    mod, bpy = lifecycle.mod, lifecycle.bpy
    world = _world(bpy.data, "Doomed")
    stray = _Object("UserCube", otype="MESH")
    world.collection.objects.append(stray)
    bpy.data.objects.append(stray)
    foreign = _Collection("UserCollection", [_Object("Other", otype="MESH")])
    bpy.data.collections.append(foreign)
    bpy.data.objects.extend(foreign.objects)
    mod.note_splats_imported()

    bpy.data.objects.remove(world.proxy)
    mod.reconcile_splats()

    assert stray in bpy.data.objects
    assert world.collection in bpy.data.collections  # still holds the user's object
    assert foreign in bpy.data.collections
    assert foreign.objects[0] in bpy.data.objects


def test_point_cloud_fallback_world_is_never_purged(lifecycle):
    mod, bpy = lifecycle.mod, lifecycle.bpy
    # KIRI's proxy step failed / the addon was unavailable: the world stays a
    # visible point cloud with no proxy, and must not read as "already deleted".
    fallback = _Collection("WorldLabs_Fallback")
    mesh = _Object("Fallback", otype="MESH")
    mod.finalize_splat_handles(fallback, [mesh], [])
    fallback.objects.append(mesh)
    bpy.data.collections.append(fallback)
    bpy.data.objects.append(mesh)
    healthy = _world(bpy.data, "Healthy")
    mod.note_splats_imported()

    bpy.data.objects.remove(healthy.proxy)
    mod.reconcile_splats()

    assert fallback in bpy.data.collections
    assert mesh in bpy.data.objects


def test_deleting_the_last_world_tears_the_runtime_down(lifecycle):
    mod, bpy, calls = lifecycle.mod, lifecycle.bpy, lifecycle.calls
    only = _world(bpy.data, "Only")
    bpy.gaussian_object_cache = {only.proxy.name: {"object": only.proxy}}
    mod.note_splats_imported()

    bpy.data.objects.remove(only.proxy)
    mod.reconcile_splats()

    assert ("cleanup", False) in calls
    assert ("texture",) not in calls


def test_readded_proxy_forces_cache_reconstruction(lifecycle):
    mod, bpy, calls = lifecycle.mod, lifecycle.bpy, lifecycle.calls
    world = _world(bpy.data, "Undone")
    bpy.gaussian_object_cache = {}  # undo restored the object, not the cache entry
    mod.note_splats_imported()
    mod._known_proxies = frozenset()

    mod.reconcile_splats()

    # A cache that cannot serve the proxy is dropped, so KIRI reconstructs it
    # from the proxy's saved gaussian_data instead of rendering nothing.
    assert not hasattr(bpy, "gaussian_object_cache")
    assert ("texture",) in calls


# --------------------------------------------------------------------------- #
# Hiding a world
# --------------------------------------------------------------------------- #

def test_hiding_a_world_also_hides_it_from_renders(lifecycle):
    mod, bpy = lifecycle.mod, lifecycle.bpy
    world = _world(bpy.data, "Room")
    mod.note_splats_imported()
    assert world.mesh.hide_render is False

    world.proxy._visible = False  # outliner eye on the proxy
    mod.on_depsgraph_update()
    assert lifecycle.timers.is_registered(mod.reconcile_splats)
    mod.reconcile_splats()
    assert world.mesh.hide_render is True

    world.proxy._visible = True
    mod.reconcile_splats()
    assert world.mesh.hide_render is False


def test_visibility_change_alone_does_not_rebuild_textures(lifecycle):
    mod, bpy, calls = lifecycle.mod, lifecycle.bpy, lifecycle.calls
    world = _world(bpy.data, "Room")
    mod.note_splats_imported()

    world.proxy.hide_viewport = True
    mod.reconcile_splats()

    # KIRI's own draw pass picks visibility up per redraw (see the patch below);
    # rebuilding the global textures for a hide would be pure waste.
    assert calls == []


# --------------------------------------------------------------------------- #
# The vendored KIRI patch
# --------------------------------------------------------------------------- #

def test_kiri_metadata_writers_use_real_visibility():
    source = _KIRI_PATH.read_text(encoding="utf-8")
    writers = re.findall(r"metadata_data\[base_idx \+ 2\] = (.+)", source)
    assert writers, "visibility slot writers vanished — re-check the KIRI vendor drop"
    for writer in writers:
        assert writer.startswith("mixar_object_visibility("), writer
    assert "def mixar_object_visibility(" in source


def test_kiri_rebuilds_metadata_when_visibility_changes():
    source = _KIRI_PATH.read_text(encoding="utf-8")
    # A hide changes no transform, so the transform check alone can never
    # refresh the visibility flags.
    assert "visibility_changed = visibility != getattr(bpy, 'mixar_last_visibility', None)" in source
    assert "if transforms_changed or visibility_changed:" in source
    assert "'mixar_last_visibility'," in source  # cleared with the rest of the runtime


def test_kiri_shader_still_culls_on_visibility():
    glsl = _VERT_GLSL.read_text(encoding="utf-8")
    assert "obj_metadata.visibility < 0.5" in glsl
