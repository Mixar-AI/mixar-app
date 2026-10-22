# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cancel a browser sign-in from the login panel.

While a sign-in waits on the browser the panel shows a status line and this
Cancel button, never a clickable "waiting" button: a click there used to
start a second sign-in and orphan the first browser tab. Cancel ends the
wait (``common/utils/sign_in.py:cancel_sign_in``) and the panel offers
Login with Browser again, so a closed tab is never a dead end.
"""

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.sign_in import (
    cancel_sign_in,
    redraw_sign_in_surfaces,
    sync_pending_flag,
)

logger = get_logger(__name__)


class MIXIE_CHAT_OT_cancel_login(Operator):
    """Stop waiting for the browser sign-in"""
    bl_idname = "mixie_chat.cancel_login"
    bl_label = "Cancel Sign-in"
    bl_description = "Stop waiting for the browser sign-in"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        if cancel_sign_in():
            wm.mixie_chat_login_error = ""
        else:
            # An open popover is not rebuilt when a sign-in ends while the
            # user is away (Blender refreshes pop-up layouts only on input or
            # a window resize), so this Cancel may be a stale one: keep the
            # failure it would otherwise hide; the click rebuilds the popover.
            logger.debug("Cancel sign-in: nothing was in flight")
        sync_pending_flag(wm)
        redraw_sign_in_surfaces(wm)
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_cancel_login,
)
