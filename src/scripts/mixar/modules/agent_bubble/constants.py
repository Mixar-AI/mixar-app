# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble constants."""

import sys


# Desktop platforms with working native bubble minimize/restore/expand controls.
BUBBLE_WINDOW_CONTROLS_SUPPORTED = sys.platform in {"darwin", "win32", "linux"}

# The island tabs that show the CHAT (transcript + composer), and the
# ``scene.mixie_chat_mode`` each one puts the chat into. ``wm.mixar_bubble_tab``
# is the one source of what the card shows; selecting a chat tab writes its
# mode (``ui/properties/bubble_tab_props.py``) and a loaded file selects the
# tab of its saved mode (``space_mixie_chat/core/file_handlers.py``). Every
# other tab is a generation/queue pane and leaves the mode alone. The C++
# twin is ``agent_ui_tab_shows_chat`` (``agent_ui_layout.hh``).
CHAT_TAB_MODES = {'AGENT': 'AGENT', 'ADDON': 'ADDON_PROJECT'}

# How far (window pixels) a press on the pill window may travel and still be
# a CLICK. Past it the press becomes a DRAG that moves the pill. The pill's
# press is decided by how it ends, never at PRESS time — see
# ui/operators/bubble_header_drag_op.py.
PILL_DRAG_THRESHOLD_PX = 4
# A pill press that has not become a click or a drag within this many
# seconds is abandoned: its RELEASE went to another window (a restore
# re-parents the pill mid-press), and a later release must not toggle the
# island that the user has meanwhile opened and is typing in.
PILL_CLICK_MAX_SECONDS = 1.5
