# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Space Header

Header definition for the Mixie Chat space.

The user-profile dropdown that used to live on the right side of this
header has moved to Blender's main top bar — see
`mixar.modules.space_mixie_chat.ui.topbar` (MIXAR_PT_profile + the
TOPBAR_HT_upper_bar.append hook). The Mixie Chat header now only
carries chat-specific controls (new-chat, dev indicator, connect
button, dev state-cycler).
"""

import bpy
from bpy.types import Header

from ..constants import DEV_MODE, SessionState
from ..core import get_session_manager


class MIXIE_CHAT_HT_header(Header):
    bl_space_type = "MIXIE_CHAT"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        wm = context.window_manager
        layout.template_header()

        # New Chat button (left side, near header menu)
        layout.operator("mixie_chat.new_session", text="", icon='FILE_NEW')

        # Past chats — New Chat archives the conversation instead of
        # destroying it; this toggles the C++-drawn history overlay in
        # the chat region (see history_ops.py + the C++ file
        # mixie_chat_history_overlay.cc). hasattr guard: UI modules
        # register in a deferred pass, so the operator may not exist for
        # the first few draws (same pattern as the login popover in
        # topbar.py).
        if hasattr(bpy.types, 'MIXIE_CHAT_OT_show_history'):
            layout.operator(
                "mixie_chat.show_history",
                text="",
                icon='TIME',
                depress=bool(getattr(wm, 'mixie_chat_history_visible', False)),
            )

        # Spacer
        layout.separator_spacer()

        # Right-side items in a separate row
        right_row = layout.row(align=True)

        # Dev mode indicator
        if DEV_MODE:
            right_row.label(text="[DEV]", icon="SCRIPT")

        # Connection status
        session = get_session_manager()
        state = session.get_state(scene)

        # Auto-sync: newly created scenes default to OFFLINE, but if the
        # WebSocket connection is already active, schedule a state sync.
        # draw() is read-only — cannot write RNA properties here.
        if state == SessionState.OFFLINE:
            from ..core.connection_manager import get_connection_manager
            if get_connection_manager().is_connected:
                scene_name = scene.name
                def _sync():
                    s = bpy.data.scenes.get(scene_name)
                    if s and hasattr(s, 'mixie_chat_state') and s.mixie_chat_state == 'OFFLINE':
                        session.set_state(s, SessionState.IDLE)
                    return None  # Run once
                bpy.app.timers.register(_sync, first_interval=0.0)
                state = SessionState.IDLE  # Show correct UI immediately

        # Connection controls (only show if logged in)
        if wm.mixie_chat_is_logged_in:
            if state == SessionState.OFFLINE:
                # Show connect button when offline; no disconnect button when connected.
                right_row.operator("mixie_chat.connect", text="Connect", icon="LINKED")

        # Dev mode: state cycling button
        if DEV_MODE and session.is_connected(scene):
            right_row.operator("mixie_chat.dev_cycle_state", text="", icon="LOOP_FORWARDS")



classes = (MIXIE_CHAT_HT_header,)
