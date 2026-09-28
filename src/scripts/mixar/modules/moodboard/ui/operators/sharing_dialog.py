# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Refresh async dialog layouts only while their temporary region is alive."""
import bpy
from ...core import sharing_flow as flow


class SharingDialog:
    def begin(self, context, width):
        self._open = True
        self._popup = None
        self._last_state = None
        self._lifecycle = flow.lifecycle
        result = context.window_manager.invoke_props_dialog(self, width=width, confirm_text="Close")
        bpy.app.timers.register(self._refresh, first_interval=.1)
        return result

    def track(self, context):
        # A draw only records its own temporary region. Never refresh from draw.
        self._popup = context.region_popup

    def _refresh(self):
        try:
            # execute/cancel end the region's lifetime; file loads/account
            # changes invalidate the epoch before a timer can reuse its pointer.
            if not self._open or self._lifecycle != flow.lifecycle:
                return None
            if flow._account != flow.identity():
                flow.sync_account()
                self._lifecycle = flow.lifecycle
                self._last_state = None
            wm = bpy.context.window_manager
            state = (wm.moodboard_community_busy, wm.moodboard_community_notice,
                     wm.moodboard_community_link, wm.moodboard_community_mode,
                     wm.moodboard_community_page, wm.moodboard_community_kind,
                     wm.moodboard_community_selected, len(flow.records))
            if state != self._last_state and self._popup:
                self._last_state = state
                self._popup.tag_refresh_ui()
        except (ReferenceError, RuntimeError):
            return None
        return .1

    def execute(self, context):
        self._open = False
        self._popup = None
        return {'FINISHED'}

    def cancel(self, context):
        self._open = False
        self._popup = None
