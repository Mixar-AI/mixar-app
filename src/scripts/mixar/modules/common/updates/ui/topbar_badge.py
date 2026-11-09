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
on the latest release. Once ready, clicking opens the same restart
confirmation as the toast button. Otherwise it re-shows the sticky update
toast, which makes suppressing repeat announcements safe: the update is
demoted to ambient status, never withheld.

Hidden while the installer stages in the background (DOWNLOADING,
signature check included): like Chrome, VS Code or Slack, the download is
silent and the badge appears once there is something to do — "Restart to
Update".
"""

import bpy

from mixar.modules.common.i18n import iface_

from ..constants import InstallState
from ..core.state import get_update_state
from ..core.update_checker import is_forced

# Install states in which the update is under way, not a problem. A
# forced update is still red while nothing is happening (the user must
# act), but once staging/installing is under way red would read as an
# error. DOWNLOADING never draws (see draw_update_badge); it stays here so
# the colour rule covers every state.
_IN_PROGRESS_STATES = (
    InstallState.DOWNLOADING,
    InstallState.READY,
    InstallState.INSTALLING,
)


def badge_alert(state, info) -> bool:
    """Whether the badge draws in the alert (red) style.

    Red only for a forced/unsupported update the user has not started on
    yet (or whose staging failed/was ruled out). In-progress states use
    the regular theme button — the same neutral as the Login pill beside
    it.
    """
    if info is None or not is_forced(info):
        return False
    return state.install_state not in _IN_PROGRESS_STATES


def badge_label(state) -> str:
    """Label for the topbar badge in the states that draw one.

    A user who dismissed the toast can still see that a restart will
    finish the job. Pure so it is unit-testable.
    """
    install_state = state.install_state
    if install_state is InstallState.READY:
        return iface_("Restart to Update")
    if install_state is InstallState.INSTALLING:
        return iface_("Updating…")
    return iface_("Update Available")


def draw_update_badge(layout) -> None:
    """Draw the update badge into *layout*.

    Draws nothing while no update is known or while the installer stages
    in the background. The download thread's main-thread follow-up
    (``install_flow._after_download`` → ``refresh_update_toast``) tags the
    topbar when staging ends, so "Restart to Update" (or "Update
    Available" after a failure) appears without user input.
    """
    state = get_update_state()
    info = state.update_info
    if info is None or state.install_state is InstallState.DOWNLOADING:
        return

    row = layout.row(align=True)
    row.alert = badge_alert(state, info)
    row.operator_context = 'INVOKE_DEFAULT'
    row.operator(
        "mixar.restart_to_update" if state.install_state is InstallState.READY
        else "mixar.show_update_toast",
        text=badge_label(state),
        translate=False,
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
