# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Credit-Upgrade Notification

The backend pushes a ``credit_upgrade`` notification (via ``notifications.push``)
when a user's credits are exhausted. The client opens the whole-window
out-of-credits banner (``credits_banner.py``) whose Upgrade button runs
``mixar.open_credit_upgrade``, which opens the manage-subscription page in the
browser via the seamless auth handoff.

Mirrors the ``update`` type's pattern: a distinct type the client recognises
and turns into client-side UI, so the backend never needs to know operator
idnames.
"""

from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Id of the retired credit-upgrade toast; the upgrade operator still dismisses
# it so a toast restored from an older session cannot linger.
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
    """Open the out-of-credits banner from a backend push payload.

    The banner replaced the sticky "Upgrade" toast this used to push: running
    out of credits blocks the user's next action, so it gets the whole window
    rather than a corner of the viewport.

    Args:
        params: The ``notifications.push`` params. Recognised keys:
            ``action_url`` (the page the Upgrade button opens: manage
            subscription for free/trial users, buy credits for paid ones) and
            an optional ``id`` (the backend sends none today).
    """
    global _pending_upgrade_url
    _pending_upgrade_url = params.get("action_url")

    from .credits_banner import request_credits_banner

    request_credits_banner(
        "push",
        action_url=params.get("action_url"),
        push_id=params.get("id") or None,
    )
    logger.info("Requested the credits banner for a credit-upgrade push")
