# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators behind the usage-meter popover's CTAs.

Purchase and plan-change flows stay on the web dashboard — the desktop
client never renders payment UI — so these just open the right page
through a one-time auth handoff, landing the browser already signed in.
"""

from __future__ import annotations

import threading

import bpy
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger

from ...constants import HANDOFF_TARGET_BUY_CREDITS
from ...core import poller

logger = get_logger(__name__)


def _resolve_url(target: str) -> str:
    """Best available URL for ``target``, preferring a seamless handoff.

    Falls back to the plain dashboard so a handoff outage degrades to "you
    have to log in again", not a dead button.
    """
    try:
        from mixar.modules.auth.core.auth import create_dashboard_handoff_url

        result = create_dashboard_handoff_url(source="usage_meter", target=target)
        if result.get("success") and result.get("url"):
            return result["url"]
        logger.warning("Usage meter handoff unavailable: %s", result.get("message"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Usage meter handoff failed: %s", exc)

    try:
        from mixar.config.config import get_frontend_url

        return "%s/app" % get_frontend_url().rstrip("/")
    except Exception as exc:  # noqa: BLE001
        logger.error("Usage meter: no fallback dashboard URL: %s", exc)
        return ""


class MIXAR_OT_open_billing(bpy.types.Operator):
    """Open your billing page in the browser"""

    bl_idname = "mixar.open_billing"
    bl_label = "Open Billing"
    bl_options = {'INTERNAL'}

    target: StringProperty(
        name="Target",
        description="Post-login destination on the web dashboard",
        default=HANDOFF_TARGET_BUY_CREDITS,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        target = self.target

        def _open() -> None:
            url = _resolve_url(target)
            if not url:
                return

            # The handoff is a network call, so it resolves off-thread; the
            # actual open must go back to the main thread (bpy.ops), and
            # webbrowser.open() is unreliable under embedded Python.
            def _fire():
                try:
                    bpy.ops.wm.url_open(url=url)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to open %s: %s", url, exc)
                return None

            bpy.app.timers.register(_fire)

        threading.Thread(target=_open, daemon=True).start()

        # The user is on their way to spend money; have a fresh number
        # waiting when they come back.
        poller.request_refresh()
        return {'FINISHED'}


class MIXAR_OT_refresh_usage(bpy.types.Operator):
    """Re-check your remaining credits"""

    bl_idname = "mixar.refresh_usage"
    bl_label = "Refresh Usage"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        poller.request_refresh()
        return {'FINISHED'}


classes = (
    MIXAR_OT_open_billing,
    MIXAR_OT_refresh_usage,
)
