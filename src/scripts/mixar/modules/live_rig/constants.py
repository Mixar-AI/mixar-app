# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for live webcam → armature drive and multi-instance pose sync."""

from __future__ import annotations

# bpy.app.timers interval for the capture / apply / sync pump.
PUMP_INTERVAL_S = 1.0 / 30.0

# Default webcam device index (OpenCV-style). Platform backends may remap this.
DEFAULT_CAMERA_INDEX = 0

# Compact pose payload version for room fan-out. Bump when the wire shape changes.
POSE_SCHEMA_VERSION = 1

# REST + WebSocket paths on the Mixar backend (see modules/live_rig_sync).
ROOM_API_PREFIX = "/api/v1/live-rig"
ROOM_WS_PATH = "/api/live-rig/ws"

# RNA / WindowManager property names.
WM_PROPS = "mixar_live_rig"
