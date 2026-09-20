# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror props for local-model download/server state.

These are WRITE-ONLY mirrors maintained by ``core/orchestrator.py``'s
main-thread pump and server-state handler; UI (the BYOK dialog's Local
provider section) only reads them. All transient (``SKIP_SAVE``) — the
authoritative state lives in the orchestrator/supervisor/manifest, so a
stale mirror after reload merely re-syncs on the next pump tick.

Hand-written register()/unregister() because WindowManager props are not
classes; unregister wipes live values first (Reload Scripts keeps the
WindowManager instance alive across module teardown).
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

_WM_ATTRS = (
    "mixar_local_dl_active",
    "mixar_local_dl_label",
    "mixar_local_dl_pct",
    "mixar_local_dl_file",
    "mixar_local_server_state",
    "mixar_local_server_model",
    "mixar_local_last_error",
)

_DEFAULTS = {
    "mixar_local_dl_active": False,
    "mixar_local_dl_label": "",
    "mixar_local_dl_pct": 0,
    "mixar_local_dl_file": "",
    "mixar_local_server_state": "",
    "mixar_local_server_model": "",
    "mixar_local_last_error": "",
}


def wipe_transient_state(wm) -> None:
    """Reset every mirror prop on a live WindowManager (logout/unregister)."""
    if wm is None:
        return
    for attr, default in _DEFAULTS.items():
        try:
            setattr(wm, attr, default)
        except Exception:
            pass


def register():
    WM = bpy.types.WindowManager
    WM.mixar_local_dl_active = BoolProperty(
        name="Local model download active", default=False,
        options={'SKIP_SAVE'},
    )
    WM.mixar_local_dl_label = StringProperty(
        name="Local model download label", default="",
        options={'SKIP_SAVE'},
    )
    WM.mixar_local_dl_pct = IntProperty(
        name="Local model download percent", default=0, min=0, max=100,
        subtype='PERCENTAGE', options={'SKIP_SAVE'},
    )
    WM.mixar_local_dl_file = StringProperty(
        name="Local model download file", default="",
        options={'SKIP_SAVE'},
    )
    WM.mixar_local_server_state = StringProperty(
        # "" | spawning | waiting_health | ready | crashed | failed | stopped
        name="Local server state", default="",
        options={'SKIP_SAVE'},
    )
    WM.mixar_local_server_model = StringProperty(
        name="Local server model", default="",
        options={'SKIP_SAVE'},
    )
    WM.mixar_local_last_error = StringProperty(
        name="Local model last error", default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    WM = bpy.types.WindowManager
    seen = set()
    candidates = []
    try:
        candidates.extend(list(bpy.data.window_managers))
    except Exception:
        pass
    try:
        candidates.append(bpy.context.window_manager)
    except Exception:
        pass
    for wm in candidates:
        marker = id(wm)
        if marker not in seen:
            seen.add(marker)
            wipe_transient_state(wm)
    for attr in _WM_ATTRS:
        try:
            delattr(WM, attr)
        except AttributeError:
            pass
