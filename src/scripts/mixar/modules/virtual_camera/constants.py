# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual Camera module constants."""

# Server
DEFAULT_PORT = 8143
PORT_SCAN_RANGE = 10          # try DEFAULT_PORT..DEFAULT_PORT+9 if taken
TOKEN_LENGTH = 16             # url-safe pairing token characters
WS_PATH = "/ws"

# Control loop
APPLY_TIMER_INTERVAL = 1.0 / 60.0   # main-thread pose apply cadence (seconds)
CONTROL_STALE_SECONDS = 1.0         # ignore control packets older than this
DEFAULT_SEND_RATE_HZ = 60
DEFAULT_MOVE_SCALE = 1.0
DEFAULT_SMOOTHING = 0.4             # 0 = raw, 0.95 = heaviest steady-cam
DEFAULT_LENS_MM = 50.0
LENS_MIN_MM = 8.0
LENS_MAX_MM = 250.0
MOVE_SPEED_BASE = 2.0               # metres/second at move_scale 1.0, full stick
PAN_SPEED_BASE = 1.6                # radians/second yaw at full right-stick x

# Streaming
DEFAULT_STREAM_FPS = 30
STREAM_FPS_MAX = 60
STREAM_QUALITY_SIZES = {1: 480, 2: 720, 3: 1080}   # short-edge pixels
DEFAULT_STREAM_QUALITY = 2
STREAM_JPEG_QUALITY = {1: 55, 2: 68, 3: 80}

# State sync
STATE_SYNC_INTERVAL = 0.25          # seconds between state pushes to the phone

# Vertigo
VERTIGO_DEFAULT_DISTANCE = 3.0      # metres, when camera has no DOF focus set

# Pairing QR (the WindowManager mirror the Cinema pairing card paints from)
QR_MAX_MODULES = 17 + 4 * 10        # MAX_VERSION in core/qr_encoder.py
QR_MATRIX_MAXLEN = QR_MAX_MODULES * QR_MAX_MODULES
