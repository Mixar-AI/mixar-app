# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression tests for restoring saved KIRI splats after a .blend load."""

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MOD_PATH = (
    _REPO_ROOT
    / "src/scripts/mixar/modules/moodboard/core/splat_render_camera.py"
)


class _Object(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name
        self.type = props.pop("type", "EMPTY")
        self.modifiers = {}
        self.hide_viewport = True
        self.hidden = True

    def hide_set(self, value):
        self.hidden = value


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
def loaded_module(monkeypatch):
    """Load the module with deterministic Blender/KIRI runtime stubs."""
    timers = _Timers()
    handlers = types.ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    app = types.ModuleType("bpy.app")
    app.handlers = handlers
    app.timers = timers
    app.background = False
    bpy = types.ModuleType("bpy")
    bpy.app = app
    bpy.data = types.SimpleNamespace(objects=[], scenes=[])

    logging_stub = types.ModuleType("mixar.config.logging_config")
    logging_stub.get_logger = lambda _name: MagicMock()
    addon_utils = types.ModuleType("addon_utils")
    addon_utils.check = lambda _name: (True, True)

    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bpy.app", app)
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", handlers)
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", logging_stub)
    monkeypatch.setitem(sys.modules, "addon_utils", addon_utils)

    spec = importlib.util.spec_from_file_location(
        "test_splat_render_camera_reload", _MOD_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, bpy, timers, addon_utils


def _install_kiri(monkeypatch, bpy, calls):
    kiri = types.ModuleType("kiri_3dgs_render")

    def cleanup(remove_objects):
        calls.append(("cleanup", remove_objects))
        for name in (
            "gaussian_draw_handle",
            "gaussian_object_cache",
            "gaussian_texture",
            "gaussian_quad_shader",
        ):
            if hasattr(bpy, name):
                delattr(bpy, name)

    def shader():
        calls.append(("shader",))
        bpy.gaussian_quad_shader = object()

    def texture():
        calls.append(("texture",))
        bpy.gaussian_object_cache = {
            obj.name: {"object": obj}
            for obj in bpy.data.objects
            if obj.get("is_gaussian_splat", False)
        }
        bpy.gaussian_texture = object()

    def viewport():
        calls.append(("viewport",))
        bpy.gaussian_draw_handle = object()

    kiri.sna_clean_up_scene_5F1F1 = cleanup
    kiri.sna_shader_system_A4AED = shader
    kiri.sna_texture_creation_FD1B2 = texture
    kiri.sna_viewport_render_A3941 = viewport
    monkeypatch.setitem(sys.modules, "kiri_3dgs_render", kiri)


def test_load_schedules_and_rehydrates_saved_proxy(
    loaded_module, monkeypatch
):
    module, bpy, timers, _addon_utils = loaded_module
    proxy = _Object(
        "RoomSplat_Proxy",
        is_gaussian_splat=True,
        gaussian_count=12,
        source_mesh_uuid="source-1",
    )
    bpy.data.objects = [proxy]
    calls = []
    _install_kiri(monkeypatch, bpy, calls)

    module.on_load_post()

    assert timers.is_registered(module.restore_splat_viewport)
    assert timers.registered[module.restore_splat_viewport] == 1.0
    assert module.restore_splat_viewport() is None
    assert calls == [
        ("cleanup", False),
        ("shader",),
        ("texture",),
        ("viewport",),
    ]
    assert "RoomSplat_Proxy" in bpy.gaussian_object_cache
    assert hasattr(bpy, "gaussian_draw_handle")


def test_splat_free_file_clears_previous_files_runtime(
    loaded_module, monkeypatch
):
    module, bpy, timers, _addon_utils = loaded_module
    bpy.gaussian_object_cache = {"OldProxy": object()}
    bpy.gaussian_draw_handle = object()
    calls = []
    _install_kiri(monkeypatch, bpy, calls)

    module.schedule_splat_viewport_restore()

    assert timers.is_registered(module.restore_splat_viewport)
    assert module.restore_splat_viewport() is None
    assert calls == [("cleanup", False)]
    assert not hasattr(bpy, "gaussian_object_cache")
    assert not hasattr(bpy, "gaussian_draw_handle")


def test_restore_retries_then_reveals_saved_source_point_cloud(loaded_module):
    module, bpy, _timers, addon_utils = loaded_module
    addon_utils.check = lambda _name: (False, False)
    module._RESTORE_MAX_ATTEMPTS = 2
    proxy = _Object(
        "RoomSplat_Proxy",
        is_gaussian_splat=True,
        gaussian_count=12,
        source_mesh_uuid="source-1",
    )
    source = _Object("RoomSplat", gaussian_source_uuid="source-1", type="MESH")
    bpy.data.objects = [proxy, source]

    assert module.restore_splat_viewport() == 1.0
    assert source.hidden is True
    assert module.restore_splat_viewport() is None
    assert source.hide_viewport is False
    assert source.hidden is False


def test_unregister_cancels_pending_restore(loaded_module):
    module, bpy, timers, _addon_utils = loaded_module
    bpy.data.objects = [
        _Object("Proxy", is_gaussian_splat=True, gaussian_count=1)
    ]
    module.schedule_splat_viewport_restore()
    assert timers.is_registered(module.restore_splat_viewport)

    module.cancel_splat_viewport_restore()

    assert not timers.is_registered(module.restore_splat_viewport)
