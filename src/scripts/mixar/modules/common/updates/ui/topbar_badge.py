# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Topbar Update Badge

Persistent "Update Available" indicator drawn just right of the topbar
"Open Mixie" button (called from agent_bubble's TOPBAR_HT_upper_bar
draw hook).  Visible whenever update info is cached in the update state
singleton — including after the user skips the version, so the badge
persists until they are actually on the latest release.  Clicking
re-shows the sticky update toast.
"""

import bpy

from ..core.state import get_update_state
from ..core.trigger import is_forced


def draw_update_badge(layout) -> None:
    """Draw the update badge into *layout*; no-op while no update is known."""
    info = get_update_state().update_info
    if info is None:
        return

    row = layout.row(align=True)
    # Red only for forced/unsupported updates; regular button otherwise.
    row.alert = is_forced(info)
    row.operator(
        "mixar.show_update_toast", text="Update Available", icon='FILE_REFRESH',
    )


def tag_topbar_redraw() -> None:
    """Tag every topbar for redraw (main thread only).

    The topbar is a global area, invisible to ``screen.areas`` — iterate
    the Mixar-exposed ``Window.global_areas`` (rna_wm_mixar.cc) and kick
    the NC_WORKSPACE notifier so the tag is picked up without user input.
    Silently degrades on builds without the RNA overlay.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in getattr(window, "global_areas", None) or ():
                if area.type == 'TOPBAR':
                    area.tag_redraw()
        workspace = bpy.context.workspace
        if workspace is not None:
            workspace.update_tag()
    except Exception:
        pass
