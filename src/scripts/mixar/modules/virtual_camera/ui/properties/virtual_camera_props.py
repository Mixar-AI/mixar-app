# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror of the Virtual Camera session, for Cinema Mode.

The pairing UI lives on the Cinema surface — a custom-drawn C++ View3D
overlay (``view3d_director_cinema_phone.cc``) that cannot reach a Python
module singleton, so the server/runtime state is projected onto RNA here.
Same contract as the Parallel Agents card mirror and the profile card's
``mixar_usage_*`` properties.

**WindowManager, never Scene**: a pairing token, a LAN URL and a live
connection are transient session state. Serialized into a shared ``.blend``
they would hand a stale, unreachable address (and a dead token) to whoever
opened the file.

``core/wm_mirror.py`` owns every write; nothing else should touch these.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from ...constants import QR_MATRIX_MAXLEN

#: Every property this module attaches to WindowManager, for a clean unregister.
_PROP_NAMES = (
    "mixar_virtual_camera_running",
    "mixar_virtual_camera_connected",
    "mixar_virtual_camera_tls",
    "mixar_virtual_camera_url",
    "mixar_virtual_camera_notice",
    "mixar_virtual_camera_qr",
    "mixar_virtual_camera_qr_size",
)

classes = ()


def register() -> None:
    wm = bpy.types.WindowManager
    wm.mixar_virtual_camera_running = BoolProperty(
        name="Virtual Camera Running",
        description="The LAN pairing server is up and reachable",
        default=False,
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_connected = BoolProperty(
        name="Phone Connected",
        description="A phone is paired and driving the camera right now",
        default=False,
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_tls = BoolProperty(
        name="Pairing Over TLS",
        description=(
            "The server is serving HTTPS. Without it iOS refuses motion "
            "sensors and the phone degrades to joystick-only control"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_url = StringProperty(
        name="Pairing URL",
        description="Address the QR code encodes, shown so it can be typed by hand",
        default="",
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_notice = StringProperty(
        name="Virtual Camera Notice",
        description="The one thing the surface should say went wrong, or empty",
        default="",
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_qr = StringProperty(
        name="QR Modules",
        description=(
            "The pairing QR as row-major '0'/'1' modules. The card paints it "
            "with the surface's own primitives — no image datablock, no "
            "preview collection and no file read on the draw path"
        ),
        default="",
        maxlen=QR_MATRIX_MAXLEN,
        options={'SKIP_SAVE'},
    )
    wm.mixar_virtual_camera_qr_size = IntProperty(
        name="QR Size",
        description="Modules per side of the QR matrix; 0 while there is nothing to scan",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )


def unregister() -> None:
    for name in _PROP_NAMES:
        try:
            delattr(bpy.types.WindowManager, name)
        except Exception:  # noqa: BLE001 — never registered / already gone
            pass
