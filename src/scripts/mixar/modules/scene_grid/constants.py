# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the Scene Grid module."""

# Redraw pump intervals (seconds). While any scene has a busy agent the grid
# is redrawn at PUMP_INTERVAL_BUSY so tiles follow the agent's edits; the C++
# side rate-limits actual re-renders per tile.
PUMP_INTERVAL_BUSY = 0.1
PUMP_INTERVAL_IDLE = 0.5
