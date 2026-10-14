# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Out-of-Credits Banner — button actions

The native banner (``MIXAR_OT_credits_banner``) reports every outcome here
exactly once, dismissal included, so destinations and telemetry live in one
Python place:

* ``UPGRADE`` — the manage-subscription page, via ``mixar.open_credit_upgrade``
  (the same signed-in handoff the chat's Upgrade CTA uses);
* ``REFER`` — the dashboard's referrals page, signed in through a handoff;
* ``CREATOR`` — the public Creator Program page (the Help menu's link);
* ``BYOK`` — the AI Provider Settings dialog (run the agent on the user's own key);
* ``MCP`` — the Connect AI Apps (MCP) dialog;
* ``DISMISS`` — ✕, Esc or a backdrop click.
"""

import threading

import bpy
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger

from ...constants import CREDITS_BANNER_CREATOR_URL, CREDITS_BANNER_REFERRAL_URL

logger = get_logger(__name__)

BANNER_ACTIONS = ("UPGRADE", "REFER", "CREATOR", "BYOK", "MCP", "DISMISS")


def _open_url_on_main(url: str) -> None:
    def _fire():
        try:
            bpy.ops.wm.url_open(url=url)
        except Exception as exc:  # noqa: BLE001
            logger.error("Credits banner: failed to open %s: %s", url, exc)
        return None

    bpy.app.timers.register(_fire)


def _open_signed_in(url: str) -> None:
    """Open a dashboard page already signed in; the plain URL if the handoff fails.

    The handoff is a network call, so it resolves off the main thread.
    """

    def _resolve():
        target = url
        try:
            from mixar.modules.auth.core.auth import create_dashboard_handoff_url

            result = create_dashboard_handoff_url(source="credits_banner", target=url)
            if result.get("success") and result.get("url"):
                target = result["url"]
            else:
                logger.warning("Credits banner handoff unavailable: %s", result.get("message"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Credits banner handoff failed: %s", exc)
        _open_url_on_main(target)

    threading.Thread(target=_resolve, daemon=True).start()


def _open_upgrade() -> None:
    try:
        bpy.ops.mixar.open_credit_upgrade()
    except Exception as exc:  # noqa: BLE001
        logger.error("Credits banner: upgrade failed to open: %s", exc)


def _open_referrals() -> None:
    _open_signed_in(CREDITS_BANNER_REFERRAL_URL)


def _open_creator_program() -> None:
    _open_url_on_main(CREDITS_BANNER_CREATOR_URL)


# Past the banner's ~0.16 s exit animation: the blocking banner modal would
# otherwise still own the window's input when the dialog opens.
_DIALOG_DELAY_SECONDS = 0.25


def _invoke_dialog_on_main(op_path: str) -> None:
    """Invoke a dialog operator (``"mixar_byok.open_dialog"``) once the banner is gone.

    Called from the action operator, so ``bpy.context.window`` is still the
    banner's window; the deferred call reopens that context.
    """
    window = getattr(bpy.context, "window", None)

    def _fire():
        try:
            wm = bpy.context.window_manager
            win = window if window in wm.windows[:] else (wm.windows[0] if wm.windows else None)
            category, name = op_path.split(".")
            op = getattr(getattr(bpy.ops, category), name)
            if win is None:
                op("INVOKE_DEFAULT")
            else:
                with bpy.context.temp_override(window=win, screen=win.screen):
                    op("INVOKE_DEFAULT")
        except Exception as exc:  # noqa: BLE001
            logger.error("Credits banner: %s failed to open: %s", op_path, exc)
        return None

    bpy.app.timers.register(_fire, first_interval=_DIALOG_DELAY_SECONDS)


def _open_byok() -> None:
    _invoke_dialog_on_main("mixar_byok.open_dialog")


def _open_mcp() -> None:
    _invoke_dialog_on_main("mixar.connect_ai")


# Module-level so the QA replay can stand in for the browser.
DESTINATIONS = {
    "UPGRADE": _open_upgrade,
    "REFER": _open_referrals,
    "CREATOR": _open_creator_program,
    "BYOK": _open_byok,
    "MCP": _open_mcp,
}


class MIXAR_OT_credits_banner_action(bpy.types.Operator):
    """Act on the out-of-credits banner choice"""

    bl_idname = "mixar.credits_banner_action"
    bl_label = "Out of Credits"
    bl_options = {"INTERNAL"}

    action: StringProperty(
        name="Action",
        description="UPGRADE, REFER, CREATOR, BYOK, MCP or DISMISS",
        default="DISMISS",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        from ...credits_banner import note_banner_closed

        action = self.action if self.action in BANNER_ACTIONS else "DISMISS"
        note_banner_closed()

        destination = DESTINATIONS.get(action)
        if destination is not None:
            destination()

        try:
            from mixar.modules.common.analytics.credits_events import (
                capture_credits_banner_action,
            )

            capture_credits_banner_action(action, context=context)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Credits banner telemetry skipped: %s", exc)
        return {"FINISHED"}


class MIXAR_OT_show_credits_banner(bpy.types.Operator):
    """Show the out-of-credits banner (support and QA)"""

    bl_idname = "mixar.show_credits_banner"
    bl_label = "Show Out-of-Credits Banner"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ...credits_banner import request_credits_banner, reset_state

        reset_state()  # an explicit request is never swallowed by the cooldown
        request_credits_banner("manual")
        return {"FINISHED"}


classes = (
    MIXAR_OT_credits_banner_action,
    MIXAR_OT_show_credits_banner,
)
