# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cycles GPU compute-device selection shared by every Mixar render path.

Blender ships with Cycles' preferences at ``compute_device_type='NONE'``,
which means CPU-only rendering — and ``scene.cycles.device = 'GPU'`` is then
a silent no-op (Cycles falls back to CPU without any warning). Every Mixar
surface that renders or bakes through Cycles resolves GPU compute through
this module, so the backend probe order, device enabling, and CPU fallback
have exactly one owner.

Policy: an explicit user choice is never overridden. A non-``NONE`` backend
in preferences is kept as-is, and a backend whose devices the user disabled
counts as "no GPU" rather than being re-enabled.
"""

import sys

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Apple GPUs only ever appear behind METAL; everywhere else prefer OptiX
# (fastest on NVIDIA), then CUDA (older NVIDIA), HIP (AMD), oneAPI (Intel).
BACKEND_ORDER_MACOS = ("METAL",)
BACKEND_ORDER_DEFAULT = ("OPTIX", "CUDA", "HIP", "ONEAPI")


def backend_probe_order(platform_key=None):
    """Backend identifiers to try, best-first, for this platform."""
    key = sys.platform if platform_key is None else platform_key
    if key.startswith("darwin"):
        return BACKEND_ORDER_MACOS
    return BACKEND_ORDER_DEFAULT


def cycles_preferences():
    """The Cycles addon preferences, or None when Cycles is unavailable."""
    try:
        return bpy.context.preferences.addons["cycles"].preferences
    except Exception:
        return None


def _gpu_devices(prefs):
    return [
        device
        for device in (getattr(prefs, "devices", None) or [])
        if getattr(device, "type", "CPU") != "CPU"
    ]


def active_gpu_backend(prefs):
    """The configured backend, or None when rendering would fall back to CPU.

    Returns None for factory ``NONE`` preferences and for backends whose GPU
    devices are all disabled — the latter is a deliberate user choice.
    """
    if prefs is None:
        return None
    backend = getattr(prefs, "compute_device_type", "NONE")
    if backend == "NONE":
        return None
    try:
        prefs.get_devices()
    except Exception:
        pass
    enabled = [d for d in _gpu_devices(prefs) if getattr(d, "use", False)]
    return backend if enabled else None


def pick_gpu_backend(prefs, order=None):
    """Probe backends best-first and enable the first one with a GPU.

    Every non-CPU device of the winning backend is enabled. Returns the
    chosen backend identifier, or None with ``compute_device_type`` restored
    when no backend exposes a GPU (e.g. a build without that backend raises
    on enum assignment, or the machine simply has no supported GPU).
    """
    if prefs is None:
        return None
    original = getattr(prefs, "compute_device_type", "NONE")
    for backend in order or backend_probe_order():
        try:
            prefs.compute_device_type = backend
        except Exception:
            # Enum item absent when the backend isn't compiled into this build.
            continue
        try:
            prefs.get_devices()
        except Exception:
            pass
        gpus = _gpu_devices(prefs)
        if gpus:
            for device in gpus:
                device.use = True
            return backend
    try:
        prefs.compute_device_type = original
    except Exception:
        pass
    return None


def ensure_gpu_compute(prefs=None):
    """Return the usable GPU backend, probing for one only on factory prefs.

    A user-configured backend (anything non-``NONE``) is respected verbatim:
    it is returned when it has enabled GPU devices and None otherwise —
    never replaced or re-enabled.
    """
    if prefs is None:
        prefs = cycles_preferences()
    if prefs is None:
        return None
    if getattr(prefs, "compute_device_type", "NONE") != "NONE":
        return active_gpu_backend(prefs)
    return pick_gpu_backend(prefs)
