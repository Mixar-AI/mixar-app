# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene defaults preserve saved projects, explicit choices and render jobs."""

import importlib.util
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def defaults(monkeypatch):
    path = ROOT / "src/scripts/mixar/bootstrap/render_defaults_module.py"
    spec = importlib.util.spec_from_file_location("render_defaults_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "bpy", MagicMock())
    monkeypatch.setattr(module, "render_device", MagicMock())
    monkeypatch.setattr(module, "render_slot", MagicMock())
    module.bpy.app.background = False
    module.bpy.app.handlers.load_post = []
    module.bpy.data.filepath = ""
    module.render_slot.busy.return_value = False
    module.render_device.use_gpu.return_value = True
    module._ready = True
    return module


class Cycles:
    def __init__(self, explicit):
        self._device = "CPU"
        self.explicit = explicit

    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, value):
        self._device = value
        self.explicit = True

    def is_property_set(self, name):
        return self.explicit


class Scene(dict):
    _ids = count(1)

    def __init__(self, engine="CYCLES", explicit_device=False):
        super().__init__()
        self.session_uid = next(self._ids)
        self.library = None
        self.render = SimpleNamespace(engine=engine, use_border=False,
                                      use_crop_to_border=False, border_min_x=0.2)
        self.cycles = Cycles(explicit_device)


def test_first_cycles_selection_and_later_manual_choices(defaults):
    scene = Scene()
    defaults.apply_scene_defaults(scene)
    assert scene.cycles.device == "GPU" and scene.render.use_border
    assert scene.render.border_min_x == 0.2
    assert not scene.render.use_crop_to_border
    scene.cycles.device = "CPU"
    scene.render.use_border = False
    defaults.apply_scene_defaults(scene)
    assert scene.cycles.device == "CPU" and not scene.render.use_border


@pytest.mark.parametrize("reason", ["busy", "background", "linked", "not_ready", "eevee"])
def test_ineligible_scenes_are_untouched(defaults, reason):
    scene = Scene()
    if reason == "busy":
        defaults.render_slot.busy.return_value = True
    elif reason == "background":
        defaults.bpy.app.background = True
    elif reason == "linked":
        scene.library = object()
    elif reason == "not_ready":
        defaults._ready = False
    else:
        scene.render.engine = "BLENDER_EEVEE"
    defaults.apply_scene_defaults(scene)
    assert scene.cycles.device == "CPU" and not scene.render.use_border
    assert not scene


@pytest.mark.parametrize("explicit_device,gpu", [(True, True), (False, False)])
def test_explicit_cpu_and_unavailable_gpu_are_respected(defaults, explicit_device, gpu):
    scene = Scene(explicit_device=explicit_device)
    defaults.render_device.use_gpu.return_value = gpu
    defaults.apply_scene_defaults(scene)
    assert scene.cycles.device == "CPU" and scene.render.use_border


def test_startup_sets_device_for_every_scene_before_cycles_is_selected(defaults):
    scenes = [Scene("BLENDER_EEVEE"), Scene(), Scene(explicit_device=True)]
    defaults.bpy.data.scenes = scenes
    defaults.apply_startup_defaults()
    assert [s.cycles.device for s in scenes] == ["GPU", "GPU", "CPU"]
    assert [s.render.use_border for s in scenes] == [False, True, True]
    scenes[0].cycles.device = "CPU"  # explicit choice before selecting Cycles
    scenes[0].render.engine = "CYCLES"
    defaults._engine_changed()
    assert scenes[0].cycles.device == "CPU"


def test_opened_project_stays_untouched_even_after_engine_switch(defaults):
    scene = Scene("BLENDER_EEVEE")
    defaults.bpy.data.scenes = [scene]
    defaults.bpy.data.filepath = "/tmp/saved.mixar"
    defaults._prepare_file()
    defaults.apply_startup_defaults()
    scene.render.engine = "CYCLES"
    defaults._engine_changed()
    assert scene.cycles.device == "CPU" and not scene.render.use_border
    assert not scene
    # A newly-created scene in the same saved document remains eligible.
    fresh = Scene()
    defaults.bpy.data.scenes.append(fresh)
    defaults._engine_changed()
    assert fresh.cycles.device == "GPU" and fresh.render.use_border


def test_notification_targets_actual_scenes_not_current_context(defaults):
    changed, active = Scene(), Scene("BLENDER_EEVEE")
    defaults.bpy.context.scene = active
    defaults.bpy.data.scenes = [active, changed]
    defaults._engine_changed()
    assert changed.cycles.device == "GPU" and changed.render.use_border
    assert active.cycles.device == "CPU" and not active.render.use_border


def test_file_new_resets_loaded_scene_guard_and_waits_for_preferences(defaults):
    scene = Scene()
    defaults.bpy.data.scenes = [scene]
    defaults.bpy.data.filepath = "/tmp/saved.mixar"
    defaults._prepare_file()
    defaults.bpy.data.filepath = ""
    defaults._prepare_file()
    defaults._engine_changed()
    assert scene.cycles.device == "CPU" and not scene.render.use_border
    defaults.apply_startup_defaults()
    assert scene.cycles.device == "GPU" and scene.render.use_border


def test_registration_and_cleanup_are_idempotent(defaults):
    defaults.register()
    defaults.register()
    assert defaults.bpy.app.handlers.load_post == [defaults._on_load]
    defaults.unregister()
    defaults.unregister()
    assert not defaults.bpy.app.handlers.load_post
    assert not defaults._ready


def test_scene_created_while_file_load_timer_waits_receives_defaults(defaults):
    saved = Scene()
    defaults.bpy.data.scenes = [saved]
    defaults.bpy.data.filepath = "/tmp/saved.mixar"
    defaults._prepare_file()
    fresh = Scene()
    defaults.bpy.data.scenes.append(fresh)
    defaults._engine_changed()  # ignored until device setup is ready
    defaults.apply_startup_defaults()
    assert saved.cycles.device == "CPU" and not saved.render.use_border
    assert fresh.cycles.device == "GPU" and fresh.render.use_border


def test_registration_survives_restricted_startup_data(defaults):
    class RestrictData:  # Blender's `_RestrictData` during startup scripts
        pass

    defaults.bpy.data = RestrictData()
    defaults.register()
    assert defaults.bpy.app.handlers.load_post == [defaults._on_load]
    defaults.bpy.msgbus.subscribe_rna.assert_called_once()
    assert not defaults._saved_scenes
