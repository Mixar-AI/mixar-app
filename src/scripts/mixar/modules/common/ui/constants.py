# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared Mixar UI row scales and density ratios for card-styled dialogs.

Must match ``UI_mixar_chrome.hh`` ``card_row_*`` and
``mixar_density_scale(Compact)``. Pill pad/height stay in C++
``interface_mixar_card_paint.hh`` because the builder measures them.
"""

CARD_ROW_HEADING = 1.6
CARD_ROW_DIVIDER = 0.6
CARD_ROW_FIELD = 1.45
CARD_ROW_CTA = 1.7
CARD_ROW_ACTION = 1.9

# Shared card-styled props-dialog width (gallery + BYOK). Profile
# (15 UI units) and Settings (460) stay local until a second consumer.
CARD_DIALOG_WIDTH = 640

# Must match MixarDensity Default/Compact control_height (44 / 32).
DENSITY_DEFAULT_HEIGHT = 44.0
DENSITY_COMPACT_HEIGHT = 32.0
DENSITY_COMPACT_SCALE = DENSITY_COMPACT_HEIGHT / DENSITY_DEFAULT_HEIGHT
