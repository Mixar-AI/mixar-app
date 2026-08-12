# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open the Agent Bubble in a small chrome-less Blender TEMP window.

Thin wrapper around the C++ operator MIXAR_OT_agent_bubble_show_window
(registered in src/source/blender/editors/space_agent_bubble/
space_agent_bubble.cc), which calls WM_window_open_temp — the same
code path Blender uses for the Preferences / Drivers Editor / Info
Log popups.

The wrapper exists because:
  1. The Window menu hook (in agent_bubble_module.py bootstrap) is
     wired to mixar.agent_bubble_open_window. Keeping the Python
     idname stable lets us avoid touching the menu hook every time we
     swap implementations.
  2. Earlier revisions tried wm.window_new_main + workspace.duplicate
     + screen.area_close from Python, all of which produce a full main
     window (with topbar + workspace tabs + statusbar) that visually
     reads as 'a second Mixar instance'. WM_window_open_temp instead
     produces a dedicated single-area window with no chrome — matching
     the original popup intent.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)


class MIXAR_OT_agent_bubble_open_window(Operator):
    """Open the Agent Bubble in its own floating window"""

    bl_idname = "mixar.agent_bubble_open_window"
    bl_label = "Open Agent Bubble Window"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.window_manager is not None

    def execute(self, context):
        # Reaching this op means the bubble is being opened — clear
        # any prior "user dismissed the bubble" intent so the workspace-
        # change autoshow path is re-armed. Safe to do unconditionally:
        # the autoshow path is gated upstream by _on_workspace_change,
        # so when this op fires it's either a manual user action or an
        # explicit autoshow trigger (file load, splash dismissal) — both
        # of which legitimately want the dismissal flag cleared.
        try:
            from mixar.bootstrap import agent_bubble_module
            agent_bubble_module.mark_user_opened()
        except Exception:  # noqa: BLE001 — never break the open path
            pass

        # NOTE: the bubble used to force scene.mixie_chat_mode back to
        # 'AGENT' here. With the Agent/Generate selector restored in the
        # composer, opening the bubble now preserves the last-used mode.

        # Restore from the minimised pill state first. ``bubble_restore``
        # is a no-op when the bubble isn't minimised, so calling it
        # unconditionally is safe and covers the "only pill is showing"
        # case the topbar "Open Agent" button needs to handle.
        restore_op = getattr(
            getattr(bpy.ops, "mixar", None), "bubble_restore", None,
        )
        if restore_op is not None:
            try:
                restore_op()
            except Exception as exc:  # noqa: BLE001 — never block the open path
                print(f"[agent_bubble] open_window: restore raised: {exc!r}")
            # Programmatic pre-focus restore, not a user maximise. Record it so
            # telemetry's dedup guard doesn't swallow the next genuine change.
            try:
                from mixar.modules.common.analytics.bubble_events import (
                    note_programmatic_bubble_state,
                )
                note_programmatic_bubble_state("maximized")
            except Exception:  # noqa: BLE001 — never block the open path
                pass

        # The C++ op handles deduplication: WM_window_open detects an
        # existing temp window of the same space type and reuses /
        # focuses it instead of opening another. The bubble always
        # opens at the C++ AGENT_BUBBLE_DEFAULT_HEIGHT (compact);
        # there's no flag to keep in sync now that the chevron-toggle
        # has been removed in favour of header-drag.
        cpp_op = getattr(
            getattr(bpy.ops, "mixar", None),
            "agent_bubble_show_window",
            None,
        )
        if cpp_op is None:
            self.report(
                {'ERROR'},
                "C++ operator mixar.agent_bubble_show_window is not "
                "registered — rebuild Mixar (make build) to pick up "
                "the agent_bubble spacetype operator.",
            )
            print("[agent_bubble] open_window: cpp op not registered")
            return {'CANCELLED'}

        try:
            result = cpp_op()
        except Exception as e:  # noqa: BLE001 — surface clearly
            self.report({'ERROR'}, f"Failed to open Agent Bubble window: {e}")
            print(f"[agent_bubble] open_window: cpp op raised: {e!r}")
            return {'CANCELLED'}

        # bpy.ops returns a set like {'FINISHED'} or {'CANCELLED'}.
        if 'CANCELLED' in result:
            return {'CANCELLED'}
        print("[agent_bubble] open_window: temp window opened via C++ op")
        return {'FINISHED'}


classes = (MIXAR_OT_agent_bubble_open_window,)
