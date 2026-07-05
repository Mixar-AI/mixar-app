# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Credit-exhausted Mixie chat message.

The toast surface is owned by ``common.notifications.credit_upgrade`` (same
mechanism as the "update available" toast). This module adds the *second*
surface the product wants: a message in the Mixie chat window carrying an
"Upgrade" call-to-action.

The CTA button reuses the toast's operator (``mixar.open_credit_upgrade``) via
the ``CREDIT_UPGRADE_CHAT_ACTION`` sentinel, so the seamless auth handoff to the
manage-subscription page is shared between both surfaces.

``add_credit_upgrade_chat_message`` mutates ``scene.mixie_chat_messages`` and
MUST be called on the main thread (a Blender operator or a main-thread timer /
``run_on_main_thread`` callback) — never directly from the WebSocket thread.
"""

import uuid

import bpy

from mixar.config.logging_config import get_logger

from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# Stable bubble-id prefix so repeated 402s / pushes refresh one notice bubble
# instead of stacking duplicates (dedupes the WS-push and the SSE-fallback
# triggers into a single message).
CREDITS_BUBBLE_PREFIX = "credit-upgrade-"

_CONTENT_MAXLEN = 4096
_DEFAULT_TITLE = "You're out of credits"
_DEFAULT_BODY = (
    "You've used your monthly credit allowance. "
    "Upgrade your plan to keep creating with Mixie."
)
_CTA_LABEL = "Upgrade"


def is_credits_exhausted_error(status_code, message: str = "") -> bool:
    """Heuristic: does this failure mean the user ran out of credits?

    True on an explicit 402, or when the error text mentions credits / usage
    allowance (covers the SSE stream error path, which only carries a string)."""
    if status_code == 402:
        return True
    text = (message or "").lower()
    return (
        "402" in text
        or "out of credits" in text
        or "usage allowance" in text
        or "upgrade your plan" in text
    )


def add_credit_upgrade_chat_message(
    scene=None,
    title: str = None,
    body: str = None,
    action_url: str = None,
) -> None:
    """Add (or refresh) a Mixie chat bubble with an "Upgrade" CTA.

    Best-effort and idempotent — safe to call from both the WS-push handler and
    the in-chat 402 fallback; prefix dedup collapses them to one bubble.

    Args:
        scene: Target scene; falls back to the active scene.
        title / body: Copy from the backend push (defaults applied if absent).
        action_url: manage-subscription URL; stashed so the shared upgrade
            operator opens the right page even without a preceding toast push.
    """
    try:
        from mixar.modules.common.notifications.credit_upgrade import (
            set_pending_upgrade_url,
        )
        set_pending_upgrade_url(action_url)
    except Exception as e:
        logger.debug(f"credit upgrade url stash skipped: {e}")

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene or not hasattr(scene, "mixie_chat_messages"):
        logger.warning("Cannot add credit-upgrade chat message - scene missing")
        return

    content = _build_content(title, body)

    # Refresh an existing notice in place instead of stacking duplicates.
    for msg in scene.mixie_chat_messages:
        if getattr(msg, "bubble_id", "").startswith(CREDITS_BUBBLE_PREFIX):
            _fill_bubble(msg, content)
            redraw_chat_areas()
            return

    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = f"{CREDITS_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
    msg.sender = "AGENT"
    msg.message_type = "AGENT"
    _fill_bubble(msg, content)

    try:
        from .animation_manager import start_slide_redraw_burst
        start_slide_redraw_burst()
    except Exception:
        pass
    redraw_chat_areas()


def _build_content(title: str, body: str) -> str:
    title = (title or _DEFAULT_TITLE).strip()
    body = (body or _DEFAULT_BODY).strip()
    return f"**{title}**\n\n{body}"[:_CONTENT_MAXLEN]


def _fill_bubble(msg, content: str) -> None:
    """Populate a bubble with markdown content + the Upgrade CTA button.

    Built manually (not via the slot pipeline) so it does NOT flip the session
    into AWAITING_INPUT the way a normal ``actions`` slot would — the user is
    not answering a prompt, they need to top up.
    """
    from mixar.modules.common.notifications.credit_upgrade import (
        CREDIT_UPGRADE_CHAT_ACTION,
    )

    msg.content = content
    msg.text = content

    # Markdown segments metadata for the C++ renderer (mirrors the slot path).
    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments

        segments = parse_markdown_to_segments(content, streaming=False)
        set_markdown_segments(msg, segments)
    except Exception as e:
        logger.debug(f"credit-upgrade markdown parse skipped: {e}")

    msg.action_items.clear()
    action = msg.action_items.add()
    action.label = _CTA_LABEL
    action.value = CREDIT_UPGRADE_CHAT_ACTION
    action.style = "PRIMARY"
