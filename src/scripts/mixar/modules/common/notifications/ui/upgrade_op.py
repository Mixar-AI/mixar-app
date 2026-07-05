# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Credit-Upgrade Toast Operator

Invoked by the "Upgrade" action button on the credit-upgrade toast. Opens the
manage-subscription page in the default browser, preferring a seamless auth
handoff (so the browser lands already logged in) and falling back to the plain
backend-supplied URL or the web dashboard.

The network handoff runs on a daemon thread so a slow request never freezes the
main thread; the toast is dismissed immediately on click.
"""

import threading
import webbrowser
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _resolve_upgrade_url(target: Optional[str]) -> Optional[str]:
    """Resolve the best URL to open, preferring a seamless auth handoff.

    1. Seamless handoff — opens the browser already logged in, redirecting to
       the subscription page when the backend honours ``target``.
    2. The plain backend-supplied subscription URL.
    3. The web dashboard as a last resort.
    """
    try:
        from mixar.modules.auth.core.auth import create_dashboard_handoff_url

        result = create_dashboard_handoff_url(source="credit_upgrade", target=target)
        if result.get("success") and result.get("url"):
            return result["url"]
        logger.warning("Upgrade handoff URL unavailable: %s", result.get("message"))
    except Exception as e:
        logger.error("Upgrade handoff URL creation failed: %s", e)

    if target:
        return target

    try:
        from mixar.config.config import get_frontend_url

        return f"{get_frontend_url()}/app"
    except Exception as e:
        logger.error("Could not resolve fallback dashboard URL: %s", e)
        return None


class MIXAR_OT_open_credit_upgrade(bpy.types.Operator):
    """Open the manage-subscription page to upgrade your plan"""

    bl_idname = "mixar.open_credit_upgrade"
    bl_label = "Upgrade Plan"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..credit_upgrade import (
            CREDIT_UPGRADE_NOTIFICATION_ID,
            get_pending_upgrade_url,
        )
        from ..store import get_notification_store

        target = get_pending_upgrade_url()

        def _open():
            url = _resolve_upgrade_url(target)
            if not url:
                logger.error("Could not resolve the upgrade page URL")
                return
            try:
                webbrowser.open(url)
            except Exception as e:
                logger.error("Failed to open upgrade URL %s: %s", url, e)

        threading.Thread(target=_open, daemon=True).start()
        get_notification_store().dismiss(CREDIT_UPGRADE_NOTIFICATION_ID)
        return {"FINISHED"}


classes = (
    MIXAR_OT_open_credit_upgrade,
)
