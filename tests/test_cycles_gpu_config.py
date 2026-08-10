# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the shared Cycles GPU compute-device selection.

``common/utils/cycles_device_utils.py`` is the single owner of the backend
probe order, device enabling, and the never-override-a-user-choice policy.
These tests exercise it with fake preference objects outside Blender, plus
source-level pins that every Cycles render path routes through it (operator
classes cannot be instantiated under the bpy stubs).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.utils import cycles_device_utils as cdu


class FakeDevice:
    def __init__(self, device_type):
        self.type = device_type
        self.use = False


class FakePrefs:
    """Mimics Cycles addon preferences: assigning an unsupported backend
    raises (enum item absent from the build), and ``get_devices()`` fills
    ``devices`` for the current backend."""

    def __init__(self, devices_by_backend, supported):
        self._by_backend = devices_by_backend
        self._supported = set(supported)
        self._backend = "NONE"
        self.devices = []

    @property
    def compute_device_type(self):
        return self._backend

    @compute_device_type.setter
    def compute_device_type(self, value):
        if value != "NONE" and value not in self._supported:
            raise TypeError("enum %r not found" % value)
        self._backend = value

    def get_devices(self):
        self.devices = self._by_backend.get(self._backend, [])


def test_probe_order_is_platform_aware():
    assert cdu.backend_probe_order("darwin") == ("METAL",)
    assert cdu.backend_probe_order("linux") == ("OPTIX", "CUDA", "HIP", "ONEAPI")
    assert cdu.backend_probe_order("win32") == ("OPTIX", "CUDA", "HIP", "ONEAPI")


DEFAULT_ORDER = ("OPTIX", "CUDA", "HIP", "ONEAPI")


def test_pick_takes_first_backend_with_a_gpu_and_enables_all_gpus():
    gpu_a, gpu_b, cpu = FakeDevice("CUDA"), FakeDevice("CUDA"), FakeDevice("CPU")
    prefs = FakePrefs(
        {"OPTIX": [], "CUDA": [gpu_a, gpu_b, cpu]},
        supported=DEFAULT_ORDER,
    )
    assert cdu.pick_gpu_backend(prefs, order=DEFAULT_ORDER) == "CUDA"
    assert prefs.compute_device_type == "CUDA"
    assert gpu_a.use and gpu_b.use
    assert cpu.use is False  # CPU devices are left alone


def test_pick_skips_backends_the_build_does_not_carry():
    gpu = FakeDevice("HIP")
    prefs = FakePrefs({"HIP": [gpu]}, supported=("HIP",))
    # OPTIX/CUDA assignments raise; the probe must carry on to HIP.
    assert cdu.pick_gpu_backend(prefs, order=DEFAULT_ORDER) == "HIP"
    assert gpu.use


def test_pick_restores_prefs_when_no_gpu_exists():
    prefs = FakePrefs(
        {"OPTIX": [], "CUDA": [FakeDevice("CPU")]},
        supported=DEFAULT_ORDER,
    )
    assert cdu.pick_gpu_backend(prefs, order=DEFAULT_ORDER) is None
    assert prefs.compute_device_type == "NONE"


def test_active_backend_requires_an_enabled_gpu():
    gpu = FakeDevice("METAL")
    prefs = FakePrefs({"METAL": [gpu]}, supported=("METAL",))
    assert cdu.active_gpu_backend(prefs) is None  # factory NONE

    prefs.compute_device_type = "METAL"
    assert cdu.active_gpu_backend(prefs) is None  # devices all disabled

    gpu.use = True
    assert cdu.active_gpu_backend(prefs) == "METAL"


def test_ensure_respects_an_explicit_user_backend():
    """A user-set backend is returned or reported unusable — never replaced."""
    metal_gpu, cuda_gpu = FakeDevice("METAL"), FakeDevice("CUDA")
    prefs = FakePrefs(
        {"METAL": [metal_gpu], "CUDA": [cuda_gpu]},
        supported=("METAL", "CUDA"),
    )
    prefs.compute_device_type = "METAL"

    # User's devices deliberately disabled: report no GPU, don't re-enable,
    # don't jump to another backend.
    assert cdu.ensure_gpu_compute(prefs) is None
    assert prefs.compute_device_type == "METAL"
    assert metal_gpu.use is False and cuda_gpu.use is False

    metal_gpu.use = True
    assert cdu.ensure_gpu_compute(prefs) == "METAL"


def test_ensure_probes_only_on_factory_none(monkeypatch):
    monkeypatch.setattr(cdu, "backend_probe_order", lambda *_: DEFAULT_ORDER)
    gpu = FakeDevice("OPTIX")
    prefs = FakePrefs({"OPTIX": [gpu]}, supported=DEFAULT_ORDER)
    assert cdu.ensure_gpu_compute(prefs) == "OPTIX"
    assert gpu.use


# --- Source-level pins: every Cycles path resolves GPU through the helper ---

SRC = ROOT / "src" / "scripts" / "mixar"


def _read(rel):
    return (SRC / rel).read_text()


def test_bake_prepare_routes_gpu_through_shared_helper():
    source = _read("modules/paint/ui/bake/utils/bake_prepare.py")
    assert "ensure_gpu_compute" in source
    assert "scene.cycles.device = bake_device" in source
    # The fallback must demote the request, not submit GPU against no backend.
    assert 'bake_device = "CPU"' in source


def test_agent_final_render_routes_gpu_through_shared_helper():
    source = _read("modules/space_mixie_chat/ui/operators/agent_final_render_ops.py")
    assert "ensure_gpu_compute" in source
    # The hand-rolled probe loop (wrong order on macOS) must not come back.
    assert '("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI")' not in source


def test_bootstrap_configures_gpu_at_startup():
    source = _read("bootstrap/cycles_gpu.py")
    assert "ensure_gpu_compute" in source
    assert "is_property_set" in source  # explicit CPU choices must survive
    assert "load_post" in source
