# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Credit-Upgrade Notification

The backend pushes a ``credit_upgrade`` notification (via ``notifications.push``)
when a user's credits are exhausted. The client renders a sticky toast with an
"Upgrade" button wired to ``mixar.open_credit_upgrade``, which opens the
manage-subscription page in the browser via the seamless auth handoff.

Mirrors the ``update`` type's pattern: a distinct type the client recognises
and turns into a toast whose action button targets a client-side operator, so
the backend never needs to know operator idnames.
"""

from typing import Optional

from mixar.config.logging_config import get_logger

from .store import NotificationAction, get_notification_store

logger = get_logger(__name__)

# Fixed id so repeated backend pushes dedupe to a single toast.
CREDIT_UPGRADE_NOTIFICATION_ID = "mixar-credit-upgrade"

# Sentinel used as a Mixie chat action-button ``value``: the chat slot-action
# operator recognises it and invokes ``mixar.open_credit_upgrade`` (reusing the
# toast's seamless-auth handoff) instead of dispatching the value to the agent.
CREDIT_UPGRADE_CHAT_ACTION = "__mixar_open_credit_upgrade__"

# Subscription/upgrade URL supplied by the backend in the notification payload,
# read by MIXAR_OT_open_credit_upgrade when the button is pressed. Stashed at
# module scope because Blender operators can't easily carry an arbitrary payload
# through the C++ toast-click dispatch.
_pending_upgrade_url: Optional[str] = None


def get_pending_upgrade_url() -> Optional[str]:
    """Return the subscription URL from the most recent credit-upgrade push."""
    return _pending_upgrade_url


def set_pending_upgrade_url(url: Optional[str]) -> None:
    """Record the manage-subscription URL for the upgrade operator to open.

    Set by every trigger that shows the notice (the WS push and the in-chat
    402 fallback) so ``mixar.open_credit_upgrade`` lands on the right page even
    when no toast push preceded the click.
    """
    global _pending_upgrade_url
    if url:
        _pending_upgrade_url = url


def push_credit_upgrade(params: dict) -> None:
    """Show the sticky credit-upgrade toast from a backend push payload.

    Args:
        params: The ``notifications.push`` params. Recognised keys: ``title``,
            ``body``, ``priority``, ``action_url`` (the manage-subscription URL).
    """
    global _pending_upgrade_url
    _pending_upgrade_url = params.get("action_url")

    get_notification_store().push(
        type_str="credit_upgrade",
        title=params.get("title", "You're out of credits"),
        body=params.get("body", "Upgrade your plan to keep generating."),
        priority=params.get("priority", "high"),
        id=CREDIT_UPGRADE_NOTIFICATION_ID,
        dismissible=True,
        actions=[
            NotificationAction(
                label="Upgrade",
                operator="mixar.open_credit_upgrade",
                style="primary",
            ),
        ],
    )
    logger.info("Pushed credit-upgrade notification")
