# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cycles compute device — the one startup pass.

Blender's `scene.cycles.device` default is `'CPU'` and its Preferences ship
with no compute device enabled, so a Cycles render on a machine with a GPU
still ran on the CPU (trace `ddf5774e`: 45-66 s per agent verification frame,
the UI starved for the whole of it).

This module turns the machine's device on ONCE, at startup, from the user's
`default_render_device` preference (`AUTO` | `GPU` | `CPU`, default `AUTO`).
That is deliberately here and not in `space_mixie_chat/core/preview_render.py`:
`docs/render-job-contract.md` forbids the render job from writing any
Preference, and `tests/test_render_job_guard.py` pins that it never does. The
job only ever sets `scene.cycles.device` for itself and restores it.

The work is deferred onto a timer so the paint preferences (which is where
`default_render_device` lives) have been loaded from disk first, and it is
skipped while a render is running — the running job reads these Preferences.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.space_mixie_chat.core import render_device

logger = get_logger(__name__)

# Long enough for the paint module to have restored preferences.json.
FIRST_PASS_DELAY_S = 2.0
RETRY_S = 5.0
MAX_ATTEMPTS = 4

_attempts = 0


def _apply() -> float | None:
    """Timer body: enable the device, or come back if a render owns it."""
    global _attempts
    _attempts += 1
    try:
        if bpy.app.is_job_running("RENDER") and _attempts < MAX_ATTEMPTS:
            return RETRY_S
        render_device.enable_gpu_device()
    except Exception as exc:
        logger.debug("Render device startup pass failed (%s); renders stay on the CPU", exc)
    return None


def register() -> None:
    global _attempts
    _attempts = 0
    try:
        bpy.app.timers.register(_apply, first_interval=FIRST_PASS_DELAY_S)
    except Exception as exc:
        logger.debug("Could not schedule the render device startup pass: %s", exc)


def unregister() -> None:
    try:
        if bpy.app.timers.is_registered(_apply):
            bpy.app.timers.unregister(_apply)
    except Exception:
        pass
