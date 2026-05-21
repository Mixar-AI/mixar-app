# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Background Dim

A single GPU draw handler that paints a semi-transparent black
"film" over the 3D viewport / MIXIE space whenever the user is
somewhere in the onboarding flow. Its only job is to make the
floating native dialogs (welcome, tour steps, completion picker,
what's-next picker) stand out from the editor behind them.

Nothing fancy — no spotlight, no tooltip, no hit-testing. The
dialogs handle all click logic themselves.
"""

from . import overlay_renderer, overlay_state

__all__ = ["overlay_renderer", "overlay_state"]
