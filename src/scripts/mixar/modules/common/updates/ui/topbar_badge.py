# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Topbar Update Badge

Persistent "Update Available" indicator drawn just right of the topbar
"Open Mixie" button (called from agent_bubble's TOPBAR_HT_upper_bar
draw hook).  Visible whenever update info is cached in the update state
singleton — including after the toast has been dismissed or the version
has already been announced, so the badge persists until they are actually
on the latest release.  Clicking re-shows the sticky update toast, which
is what makes suppressing repeat announcements safe: the update is
demoted to ambient status, never withheld.
"""

import bpy

from ..constants import InstallState
from ..core.state import get_update_state
from ..core.update_checker import is_forced

def badge_label(state) -> str:
    """Label for the topbar badge — the always-visible install status.

    A user who dismissed the toast can still see that a download is
    running or that a restart will finish the job. Pure so it is
    unit-testable; the 1s progress tick keeps the topbar redrawing while
    a download runs.
    """
    install_state = state.install_state
    if install_state is InstallState.READY:
        return "Restart to Update"
    if install_state is InstallState.INSTALLING:
        return "Updating…"
    if install_state is InstallState.DOWNLOADING:
        progress = state.download_progress
        if progress > 0:
            return f"Downloading {int(round(progress * 100))}%"
        return "Downloading…"
    return "Update Available"


def draw_update_badge(layout) -> None:
    """Draw the update badge into *layout*; no-op while no update is known."""
    state = get_update_state()
    info = state.update_info
    if info is None:
        return

    row = layout.row(align=True)
    # Red only for forced/unsupported updates; regular button otherwise.
    row.alert = is_forced(info)
    row.operator(
        "mixar.show_update_toast",
        text=badge_label(state),
        icon='FILE_REFRESH',
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
