# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the agent viewport lock (halo + input block)."""

# --- Halo (breathing green inner-glow border) ---------------------------

# Mixar green.
HALO_COLOR = (0.290, 0.870, 0.502)

# Inner-glow band width in unscaled UI px (scaled by ui_scale at draw).
HALO_BAND = 130.0

# Breathing: peak edge alpha oscillates between MIN and MAX on a sine
# of HALO_PERIOD_S.
HALO_ALPHA_MIN = 0.07
HALO_ALPHA_MAX = 0.18
HALO_PERIOD_S = 2.6

# Falloff shape: alpha = peak * (1 - t)^exp across the band, sampled in
# HALO_STEPS sub-bands. A high exponent concentrates the light into a
# thin bright lip at the very edge that fades softly inward — reads as
# a real bloom rather than a flat coloured strip.
HALO_FALLOFF_EXP = 2.8
HALO_STEPS = 8

# Redraw cadence while executing (drives the breathing animation).
HALO_TICK_ACTIVE_S = 0.05
HALO_TICK_IDLE_S = 0.3


# --- Input block --------------------------------------------------------

# Self-check cadence for the modal so it stops promptly when the agent
# finishes (before the user's next click).
BLOCK_TIMER_S = 0.05

# Events ALWAYS passed through, even over the viewport — camera
# navigation, cursor movement, and bare modifiers. Trackpad gestures
# (Mac pinch-zoom / two-finger pan) included.
NAV_PASS_TYPES = frozenset({
    "MOUSEMOVE", "INBETWEEN_MOUSEMOVE",
    "MIDDLEMOUSE",
    "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "MOUSEPAN", "MOUSEZOOM", "MOUSEROTATE",
    "TRACKPADPAN", "TRACKPADZOOM",
    "TIMER", "TIMER_REPORT", "NONE",
    # Bare modifiers — never an edit on their own.
    "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL",
    "LEFT_ALT", "RIGHT_ALT", "OSKEY",
})

# Numpad view keys + frame-view — these only change the camera, so
# they stay usable while the agent works.
VIEW_KEY_PASS_TYPES = frozenset({
    "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
    "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
    "NUMPAD_PERIOD", "NUMPAD_PLUS", "NUMPAD_MINUS",
    "HOME",          # frame all
    "ACCENT_GRAVE",  # view pie menu
})

# Events CONSUMED when the pointer is over a 3D viewport — clicks and
# the common edit/transform hotkeys. Blocking the mouse buttons stops
# all selection + gizmo interaction; the keys stop keyboard edits on
# any lingering selection.
BLOCK_MOUSE_TYPES = frozenset({"LEFTMOUSE", "RIGHTMOUSE", "BUTTON4MOUSE", "BUTTON5MOUSE"})
BLOCK_KEY_TYPES = frozenset({
    "G", "R", "S", "E", "I", "X", "DEL", "TAB",
})
