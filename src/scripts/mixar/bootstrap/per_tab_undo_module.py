# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-tab undo: the config kill switch (design M5).

Per-tab undo is on by default in the C side (``BKE_undo_tabs.hh``): undo,
redo and Undo History in a scene tab walk that tab only, the hold is the undo
operators' own poll, and Edit > Undo Whole Document is the document-wide walk.
Two switches turn it off for a session, both read once at startup:

- the environment: ``MIXAR_PER_TAB_UNDO=0`` (the C side reads it);
- the config: ``"per_tab_undo": false`` in ``config/mixar.json`` (bundled or
  the user's ``mixar/mixar.json``), applied here through
  ``WindowManager.mixar_per_tab_undo``.

Turning it off forgets every tab's undo cursor; the document-wide walk that
follows re-reads every datablock, so the switch is safe mid-session too. With
it off the Python undo shield and the Edit-menu hold text run again.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

CONFIG_KEY = "per_tab_undo"


def apply_config() -> bool:
    """Apply the config key once; returns the resulting flag state."""
    wm = bpy.context.window_manager
    if not hasattr(wm, "mixar_per_tab_undo"):
        return False
    try:
        from mixar.config.config import get_config
        value = get_config().get(CONFIG_KEY)
    except Exception:  # noqa: BLE001 — config unreadable: keep the build default
        value = None
    if value is not None and bool(value) != bool(wm.mixar_per_tab_undo):
        wm.mixar_per_tab_undo = bool(value)
    state = bool(wm.mixar_per_tab_undo)
    logger.info("per-tab undo %s (%s)", "on" if state else "off",
                "config" if value is not None else "default")
    return state


def _apply_when_ready():
    try:
        apply_config()
    except Exception:  # noqa: BLE001
        logger.debug("per-tab undo config not applied", exc_info=True)
    return None


def register():
    # The window manager exists once the startup file is loaded; a timer tick
    # is the earliest safe moment from a bootstrap module.
    try:
        bpy.app.timers.register(_apply_when_ready, first_interval=0.0)
    except Exception:  # noqa: BLE001
        logger.debug("per-tab undo config timer not registered", exc_info=True)


def unregister():
    pass
