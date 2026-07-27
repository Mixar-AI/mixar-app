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

        session = get_session_manager()
        state = session.get_state(scene)

        # New-chat and past-chats are hidden while a turn is executing:
        # switching or clearing the conversation mid-run would detach the
        # UI from the turn the agent is still working on.
        agent_running = state in (SessionState.BUSY, SessionState.MODIFYING)

        if not agent_running:
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
                    icon='RECOVER_LAST',
                    depress=bool(getattr(wm, 'mixie_chat_history_visible', False)),
                )

            # Project rules — toggles the C++-drawn rules overlay in the
            # chat region (same style as the past-chats overlay; see
            # rules_ops.py / mixie_chat_rules_overlay.cc). The label flips
            # to "Rules" once rules exist; depress mirrors the overlay
            # being open, like the Past Chats button. hasattr guard:
            # deferred UI registration pass.
            if hasattr(bpy.types, 'MIXIE_CHAT_OT_add_rules'):
                has_rules = bool(
                    (getattr(scene, 'mixie_chat_rules', '') or '').strip()
                )
                layout.operator(
                    "mixie_chat.add_rules",
                    text="Rules" if has_rules else "Add Rules",
                    icon='TEXT',
                    depress=bool(getattr(wm, 'mixie_chat_rules_visible', False)),
                )

        # Spacer
        layout.separator_spacer()

        # Right-side items in a separate row
        right_row = layout.row(align=True)

        # Dev mode indicator
        if DEV_MODE:
            right_row.label(text="[DEV]", icon="SCRIPT")

        # Auto-sync: newly created scenes default to OFFLINE, but if the
        # WebSocket connection is already active, schedule a state sync.
        # draw() is read-only — cannot write RNA properties here.
        # is_transport_live (not is_connected): a silently dead socket keeps
        # is_connected True until the teardown watchdog, and syncing to IDLE
        # off a zombie would paint a fresh scene as Connected with no network.
        if state == SessionState.OFFLINE:
            from ..core.connection_manager import get_connection_manager
            if get_connection_manager().is_transport_live:
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
            elif state != SessionState.CONNECTING:
                # Transport can be down while session state preserves an
                # active turn (BUSY etc. survive WS loss so resumed tool
                # calls aren't rejected) — surface that instead of implying
                # a healthy connection. is_transport_live trips on recv
                # silence within seconds; is_connected only flips at the
                # 45s teardown watchdog.
                from ..core.connection_manager import get_connection_manager
                if not get_connection_manager().is_transport_live:
                    right_row.label(text="Reconnecting", icon="SORTTIME")

        # Dev mode: state cycling button
        if DEV_MODE and session.is_connected(scene):
            right_row.operator("mixie_chat.dev_cycle_state", text="", icon="LOOP_FORWARDS")



classes = (MIXIE_CHAT_HT_header,)
