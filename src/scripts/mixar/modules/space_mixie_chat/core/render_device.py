# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Cycles compute device, decided by the user and applied once at startup.

Blender ships with `scene.cycles.device = 'CPU'` and nothing in Mixar ever
wrote it, so every Cycles render — the user's F12 and the agent's
`render_viewport(quality="final")` alike — ran on the CPU on a machine with a
perfectly good GPU (trace `ddf5774e`: three finals, `device: CPU`, 45-66 s
each, the UI starved for all of it). The backend cannot fix that: it has no
idea what silicon is in the machine, the handshake's `device_id` is the
anti-abuse id and not a GPU, and `docs/render-job-contract.md` forbids the
render job from writing a Preference.

So the decision is the client's, and it is split in two:

- **Here, once at startup** (`enable_gpu_device`, driven by
  `bootstrap/render_device_module.py`): read the `default_render_device`
  preference and, unless it says CPU, turn on the machine's Metal / OptiX /
  CUDA / HIP / oneAPI device in the Cycles add-on Preferences. This is the
  only Preference write, it happens before any render, and it is idempotent.
- **In `preview_render._apply_settings`, per job**: `scene.cycles.device` is
  set to `'GPU'` for the job and restored afterwards, but ONLY when
  `use_gpu()` says the preference allows it and a device is actually enabled.
  That module must not mention `preferences.addons` at all
  (`tests/test_render_job_guard.py`), which is the other reason the read
  lives here.

Everything degrades to the CPU in silence: no device, no Cycles add-on, a
preference of CPU, or any exception at all just means `use_gpu()` is False.
"""

import bpy

from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Best first: OptiX beats CUDA on the same NVIDIA card, and a machine only ever
# has one of METAL / HIP / ONEAPI to offer.
DEVICE_TYPES = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")
PREFERENCE = "default_render_device"

# The startup pass is once per session: the enabled flags live in the user's
# Preferences and survive, so a second pass would only re-write what is there.
_startup_done = False


def preference() -> str:
    """``AUTO`` | ``GPU`` | ``CPU`` — the user's choice, AUTO when unreadable."""
    try:
        prefs = getattr(bpy.context.scene, "mixar_paint_preferences", None)
        value = str(getattr(prefs, PREFERENCE, "") or "").upper()
    except Exception:
        return "AUTO"
    return value if value in ("AUTO", "GPU", "CPU") else "AUTO"


def _cycles_preferences():
    """The Cycles add-on preferences, or None when Cycles is not loaded."""
    addon = bpy.context.preferences.addons.get("cycles")
    return getattr(addon, "preferences", None) if addon is not None else None


def _enabled_devices(cycles_prefs) -> list:
    """Every non-CPU device Cycles currently has switched on."""
    devices = []
    for device in getattr(cycles_prefs, "devices", ()) or ():
        if str(getattr(device, "type", "CPU")) != "CPU" and bool(getattr(device, "use", False)):
            devices.append(device)
    return devices


def gpu_enabled() -> bool:
    """Is a compute device switched on right now? A pure read, no writes."""
    try:
        cycles_prefs = _cycles_preferences()
        if cycles_prefs is None:
            return False
        if str(getattr(cycles_prefs, "compute_device_type", "NONE")) == "NONE":
            return False
        return bool(_enabled_devices(cycles_prefs))
    except Exception:
        return False


def use_gpu() -> bool:
    """May a Cycles job set ``scene.cycles.device = 'GPU'``?

    Both halves must hold: the preference allows it (AUTO or GPU) and a device
    is actually enabled. This is what `preview_render` calls.
    """
    return preference() != "CPU" and gpu_enabled()


def enable_gpu_device(force: bool = False) -> str:
    """Turn the machine's compute device on in Cycles' Preferences, once.

    Returns the ``compute_device_type`` in force afterwards, or ``""`` when
    nothing was enabled (CPU preference, no Cycles, no device, or a render was
    running and the pass was skipped). Safe to call repeatedly.
    """
    global _startup_done
    if _startup_done and not force:
        return ""
    if preference() == "CPU":
        _startup_done = True
        return ""
    try:
        # Never write Preferences under a running render: the job reads them.
        if bpy.app.is_job_running("RENDER"):
            return ""
        cycles_prefs = _cycles_preferences()
        if cycles_prefs is None:
            return ""

        chosen = str(getattr(cycles_prefs, "compute_device_type", "NONE") or "NONE")
        if chosen == "NONE":
            available = _available_types(cycles_prefs)
            chosen = next((name for name in DEVICE_TYPES if name in available), "")
            if not chosen:
                _startup_done = True
                logger.debug("No Cycles compute device available; renders stay on the CPU")
                return ""
            cycles_prefs.compute_device_type = chosen

        # get_devices() populates the list for the chosen backend.
        if hasattr(cycles_prefs, "get_devices"):
            cycles_prefs.get_devices()
        enabled = 0
        for device in getattr(cycles_prefs, "devices", ()) or ():
            if str(getattr(device, "type", "CPU")) == chosen and not getattr(device, "use", False):
                device.use = True
                enabled += 1
        _startup_done = True
        logger.info("Cycles compute device: %s (%d device(s) newly enabled)", chosen, enabled)
        return chosen
    except Exception as exc:
        # A machine without a GPU, a Cycles build without the backend, a
        # read-only preferences file — all of it just means CPU.
        logger.debug("Could not enable a Cycles compute device (%s); staying on the CPU", exc)
        _startup_done = True
        return ""


def _available_types(cycles_prefs) -> set:
    """The backends this build offers, from the RNA enum of the preference."""
    try:
        items = cycles_prefs.bl_rna.properties["compute_device_type"].enum_items
        return {str(item.identifier) for item in items}
    except Exception:
        return set()


def reset_for_tests() -> None:
    """Forget the once-per-session latch (tests only)."""
    global _startup_done
    _startup_done = False
