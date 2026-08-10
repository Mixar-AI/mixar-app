# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Startup Cycles GPU auto-configuration.

A fresh install renders Cycles on the CPU: preferences default to
``compute_device_type='NONE'`` and stock Blender enables no GPU backend
until the user visits Preferences → System. Mixar's audience should not
need to know that screen exists, so startup enables the platform's best
backend — but only while the preference is still factory ``NONE``. An
explicit user choice (any non-NONE backend, or deliberately disabled
devices) is never overridden; the probe/override policy lives in
``common/utils/cycles_device_utils.py``.

Scenes whose ``cycles.device`` property was never written are switched to
'GPU' once a backend is live. ``is_property_set()`` distinguishes "the
user chose CPU" (stored in the .blend / set via UI) from "never touched",
so an explicit CPU choice survives. Mixar builds also flip the native
default to 'GPU' (the ``src/intern/cycles/blender/addon/properties.py``
overlay), which makes this scene pass a no-op there — it stays as the
fallback for builds without the overlay and for files predating it.

Preferences are configured in-session on every launch rather than saved to
userpref.blend — the probe is idempotent and cheap, and never persisting
means we never overwrite a preferences file behind the user's back.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils import cycles_device_utils

logger = get_logger(__name__)

# Off the critical startup path; devices enumerate in the background timer.
_CONFIG_DELAY_S = 2.0

# Probe once per session; scene defaulting re-runs on every file load.
_probe_done = False
_backend = None


def _default_scene_devices_to_gpu() -> int:
    """Point untouched scenes at GPU rendering; count how many changed."""
    changed = 0
    for scene in bpy.data.scenes:
        cycles = getattr(scene, "cycles", None)
        if cycles is None:
            continue
        try:
            if not cycles.is_property_set("device") and cycles.device != "GPU":
                cycles.device = "GPU"
                changed += 1
        except Exception:
            logger.debug("Could not default scene %r to GPU", scene.name)
    return changed


def _configure() -> None:
    global _probe_done, _backend
    if not _probe_done:
        _backend = cycles_device_utils.ensure_gpu_compute()
        _probe_done = True
        if _backend is None:
            logger.info(
                "Cycles GPU auto-config: no GPU compute device available; "
                "rendering stays on CPU"
            )
        else:
            logger.info("Cycles GPU auto-config: %s backend active", _backend)
    if _backend is not None:
        changed = _default_scene_devices_to_gpu()
        if changed:
            logger.info(
                "Cycles GPU auto-config: defaulted %d scene(s) to GPU rendering",
                changed,
            )


def _startup_configure():
    try:
        _configure()
    except Exception:
        logger.exception("Cycles GPU auto-configuration failed")
    return None  # one-shot timer


@persistent
def _on_load_post(*_args) -> None:
    # Newly opened files bring their own scenes; give the untouched ones the
    # same GPU default. The probe itself only ever runs once per session.
    try:
        if _probe_done:
            _configure()
    except Exception:
        logger.exception("Cycles GPU scene defaulting failed on file load")


def register() -> None:
    bpy.app.timers.register(
        _startup_configure, first_interval=_CONFIG_DELAY_S, persistent=True
    )
    handlers = bpy.app.handlers.load_post
    if _on_load_post not in handlers:
        handlers.append(_on_load_post)
    logger.debug("cycles_gpu bootstrap registered")


def unregister() -> None:
    try:
        if bpy.app.timers.is_registered(_startup_configure):
            bpy.app.timers.unregister(_startup_configure)
    except Exception:
        pass
    handlers = bpy.app.handlers.load_post
    if _on_load_post in handlers:
        handlers.remove(_on_load_post)
