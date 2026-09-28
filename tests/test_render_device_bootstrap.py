# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Startup/file-load ordering and long render reservations."""

from unittest.mock import MagicMock

import pytest

from mixar.bootstrap import render_defaults_module as defaults
from mixar.bootstrap import render_device_module as startup


@pytest.fixture
def boot(monkeypatch):
    fake = MagicMock()
    fake.app.background = False
    fake.app.is_job_running.return_value = False
    fake.app.timers.is_registered.return_value = False
    fake.data.filepath = ""
    monkeypatch.setattr(startup, "bpy", fake)
    monkeypatch.setattr(defaults, "bpy", fake)
    monkeypatch.setattr(startup, "render_device", MagicMock())
    monkeypatch.setattr(startup, "render_slot", MagicMock())
    startup.render_slot.busy.return_value = False
    monkeypatch.setattr(defaults, "apply_startup_defaults", MagicMock())
    monkeypatch.setattr(startup, "_attempts", 0)
    monkeypatch.setattr(defaults, "_saved_scenes", set())
    monkeypatch.setattr(defaults, "_ready", True)
    return startup


@pytest.mark.parametrize("native", [False, True])
def test_long_renders_do_not_exhaust_startup_retries(boot, native):
    boot.bpy.app.is_job_running.return_value = native
    boot.render_slot.busy.return_value = not native
    for _ in range(boot.MAX_ATTEMPTS + 2):
        assert boot._apply() == boot.RETRY_S
    boot.render_device.enable_gpu_device.assert_not_called()
    defaults.apply_startup_defaults.assert_not_called()
    boot.bpy.app.is_job_running.return_value = False
    boot.render_slot.busy.return_value = False
    assert boot._apply() is None
    boot.render_device.enable_gpu_device.assert_called_once()
    defaults.apply_startup_defaults.assert_called_once()


def test_file_load_only_schedules_until_preferences_have_loaded(boot):
    defaults._on_load(None)
    assert not defaults._ready
    boot.render_device.enable_gpu_device.assert_not_called()
    defaults.apply_startup_defaults.assert_not_called()
    boot.bpy.app.timers.register.assert_called_once_with(
        boot._apply, first_interval=boot.FIRST_PASS_DELAY_S)
    assert boot._apply() is None
    defaults.apply_startup_defaults.assert_called_once()


def test_late_preferences_registration_is_retried(boot):
    boot.bpy.context.scene.mixar_paint_preferences = None
    assert boot._apply() == boot.RETRY_S
    defaults.apply_startup_defaults.assert_not_called()
    boot.bpy.context.scene.mixar_paint_preferences = object()
    assert boot._apply() is None
    defaults.apply_startup_defaults.assert_called_once()
