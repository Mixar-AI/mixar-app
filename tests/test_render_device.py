# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Cycles compute device: the user's preference, applied once at startup.

`docs/render-job-contract.md` forbids the render job from writing any
Preference, so the enabling lives in `bootstrap/render_device_module.py` /
`space_mixie_chat/core/render_device.py` and `preview_render` only ever reads
the answer. These tests run outside Blender with `bpy` mocked.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/render_device.py"
PREVIEW = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/preview_render.py"
BOOTSTRAP = ROOT / "src/scripts/mixar/bootstrap/render_device_module.py"


def _device(kind, use=False):
    return SimpleNamespace(type=kind, use=use)


def _cycles_prefs(compute="NONE", available=("METAL", "NONE"), devices=None):
    prefs = SimpleNamespace(
        compute_device_type=compute,
        devices=list(devices if devices is not None else [_device("METAL"), _device("CPU")]),
    )
    prefs.get_devices = lambda: None
    prefs.bl_rna = SimpleNamespace(properties={
        "compute_device_type": SimpleNamespace(
            enum_items=[SimpleNamespace(identifier=name) for name in available])})
    return prefs


@pytest.fixture
def device(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "mixar.modules.space_mixie_chat.core.render_device_under_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = MagicMock(name="bpy")
    fake.app.is_job_running.return_value = False
    monkeypatch.setattr(module, "bpy", fake)
    module.reset_for_tests()
    return module


def _install(device_module, prefs, preference="AUTO"):
    addon = SimpleNamespace(preferences=prefs) if prefs is not None else None
    device_module.bpy.context.preferences.addons.get.return_value = addon
    device_module.bpy.context.scene.mixar_paint_preferences = SimpleNamespace(
        default_render_device=preference)


# ── the startup pass ────────────────────────────────────────────────────


def test_startup_enables_the_machines_device_once(device):
    prefs = _cycles_prefs()
    _install(device, prefs)
    assert device.enable_gpu_device() == "METAL"
    assert prefs.compute_device_type == "METAL"
    assert [d.use for d in prefs.devices] == [True, False]  # the CPU entry is left alone
    assert device.gpu_enabled() is True and device.use_gpu() is True

    # Idempotent: a second pass is a no-op, and re-running it changes nothing.
    assert device.enable_gpu_device() == ""
    assert device.enable_gpu_device(force=True) == "METAL"
    assert [d.use for d in prefs.devices] == [True, False]


def test_an_already_configured_backend_is_respected(device):
    prefs = _cycles_prefs(compute="CUDA", available=("CUDA", "OPTIX", "NONE"),
                          devices=[_device("CUDA"), _device("OPTIX")])
    _install(device, prefs)
    assert device.enable_gpu_device() == "CUDA"
    assert prefs.compute_device_type == "CUDA"
    assert [d.use for d in prefs.devices] == [True, False]


def test_the_cpu_preference_never_writes_a_preference(device):
    prefs = _cycles_prefs()
    _install(device, prefs, preference="CPU")
    assert device.enable_gpu_device() == ""
    assert prefs.compute_device_type == "NONE"
    assert all(not d.use for d in prefs.devices)
    # ...and a device someone else enabled is still not used by the job.
    prefs.compute_device_type, prefs.devices[0].use = "METAL", True
    assert device.gpu_enabled() is True
    assert device.use_gpu() is False


def test_a_machine_with_no_device_stays_on_the_cpu(device):
    prefs = _cycles_prefs(available=("NONE",), devices=[_device("CPU")])
    _install(device, prefs)
    assert device.enable_gpu_device() == ""
    assert prefs.compute_device_type == "NONE"
    assert device.use_gpu() is False


def test_no_cycles_addon_is_not_an_error(device):
    _install(device, None)
    assert device.enable_gpu_device() == ""
    assert device.gpu_enabled() is False and device.use_gpu() is False


def test_a_running_render_defers_the_pass_instead_of_writing_under_it(device):
    prefs = _cycles_prefs()
    _install(device, prefs)
    device.bpy.app.is_job_running.return_value = True
    assert device.enable_gpu_device() == ""
    assert prefs.compute_device_type == "NONE"
    # The latch did not close, so the next attempt still does the work.
    device.bpy.app.is_job_running.return_value = False
    assert device.enable_gpu_device() == "METAL"


def test_an_unreadable_preference_reads_as_auto(device):
    _install(device, _cycles_prefs())
    device.bpy.context.scene.mixar_paint_preferences = None
    assert device.preference() == "AUTO"
    device.bpy.context.scene.mixar_paint_preferences = SimpleNamespace(
        default_render_device="banana")
    assert device.preference() == "AUTO"


# ── where the write is allowed to live ──────────────────────────────────


def test_the_render_job_still_writes_no_preference():
    """The contract's rule, pinned from this side too: the enabling is the
    startup module's, and the job only reads ``use_gpu()``."""
    preview = PREVIEW.read_text()
    assert "preferences.addons" not in preview
    assert "compute_device_type" not in preview
    assert "render_device.use_gpu()" in preview
    assert 'set_value(scene.cycles, "device", "GPU")' in preview

    startup = BOOTSTRAP.read_text()
    assert "enable_gpu_device" in startup
    # The startup pass never renders and never runs inside one.
    assert "bpy.ops.render" not in startup
    assert 'is_job_running("RENDER")' in startup


def test_the_preference_exists_next_to_the_bake_device():
    prefs = (ROOT / "src/scripts/mixar/modules/paint/ui/properties"
             / "preferences_properties.py").read_text()
    assert "default_render_device" in prefs and "default_bake_device" in prefs
    for choice in ("'AUTO'", "'GPU'", "'CPU'"):
        assert choice in prefs, choice
    panel = (ROOT / "src/scripts/mixar/modules/paint/ui/panels"
             / "preferences_panel_helpers.py").read_text()
    assert 'col.prop(prefs, "default_render_device")' in panel


def test_the_operator_carries_the_size_and_engine():
    ops = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators"
           / "agent_preview_render_ops.py").read_text()
    for needle in ("width: bpy.props.IntProperty", "height: bpy.props.IntProperty",
                   "engine: bpy.props.StringProperty", "width=self.width",
                   "height=self.height", "engine=self.engine"):
        assert needle in ops, needle


def test_the_contract_documents_the_device_rule_and_the_final_cap():
    doc = (ROOT / "docs/render-job-contract.md").read_text()
    for needle in ("default_render_device", "FINAL_MAX_EDGE_PX", "1920",
                   "render_device_module", "scene.cycles.device"):
        assert needle in doc, needle
