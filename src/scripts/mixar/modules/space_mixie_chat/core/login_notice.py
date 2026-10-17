# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sign-in required Mixie chat message — the guest sibling of ``credits_notice``.

A guest's turn is refused by the backend (JSON-RPC ``-32021``) or one of its
paid tools refuses mid-turn (the ``login_required`` stream event). Both carry
a ``cta`` naming what fixes it, and this module turns it into one notice
bubble with the matching buttons:

- ``login`` — Sign in.
- ``login_or_byok`` — Sign in, or Add your own key (the BYOK dialog).
- ``fix_byok`` — Fix key (the BYOK dialog), or Sign in.

The buttons are client-local actions: the slot-action operator recognises the
sentinels below and runs ``mixie_chat.login`` / ``mixar_byok.open_dialog``
instead of dispatching a value to the agent. Main thread only (mutates
``scene.mixie_chat_messages``).
"""

import uuid

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.auth.core.guest import CTA_FIX_BYOK, CTA_LOGIN, CTA_LOGIN_OR_BYOK
from mixar.modules.common.i18n import iface_, n_, rpt_

from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# Stable bubble-id prefix: repeated refusals refresh one notice, never stack.
LOGIN_BUBBLE_PREFIX = "login-required-"

# Action-button ``value`` sentinels, handled client-side by chat_special_ops.
SIGN_IN_CHAT_ACTION = "__mixar_sign_in__"
BYOK_DIALOG_CHAT_ACTION = "__mixar_open_byok_dialog__"

_CONTENT_MAXLEN = 4096

#: cta -> (title, default body)
_COPY = {
    CTA_LOGIN: (
        n_("Sign in to continue"),
        n_("Sign in to Mixar to use this."),
    ),
    CTA_LOGIN_OR_BYOK: (
        n_("Sign in to use Mixar models, or add your own key"),
        n_("Mixar models need a Mixar account. Your own API key works without one."),
    ),
    CTA_FIX_BYOK: (
        n_("Your model key isn't working"),
        n_("Fix the key in AI Provider Settings, or sign in to use Mixar models."),
    ),
}

#: cta -> ((label, action, style), ...) in display order; the first is primary.
_BUTTONS = {
    CTA_LOGIN: ((n_("Sign in"), SIGN_IN_CHAT_ACTION),),
    CTA_LOGIN_OR_BYOK: (
        (n_("Sign in"), SIGN_IN_CHAT_ACTION),
        (n_("Add your own key"), BYOK_DIALOG_CHAT_ACTION),
    ),
    CTA_FIX_BYOK: (
        (n_("Fix key"), BYOK_DIALOG_CHAT_ACTION),
        (n_("Sign in"), SIGN_IN_CHAT_ACTION),
    ),
}


def notice_buttons(cta: str):
    """``[(label, action_value), ...]`` for a cta (unknown ctas get Sign in)."""
    return list(_BUTTONS.get(cta) or _BUTTONS[CTA_LOGIN])


def add_login_required_chat_message(scene=None, cta: str = CTA_LOGIN, body: str = "") -> None:
    """Add (or refresh) the sign-in notice bubble for ``cta``.

    ``body`` is the backend's already-worded message when it sent one; the
    title is the client's, so every cta reads the same whatever the server
    text said.
    """
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene or not hasattr(scene, "mixie_chat_messages"):
        logger.warning("Cannot add sign-in chat message - scene missing")
        return

    title, default_body = _COPY.get(cta) or _COPY[CTA_LOGIN]
    content = f"**{rpt_(title)}**\n\n{(body or rpt_(default_body)).strip()}"[:_CONTENT_MAXLEN]

    for msg in scene.mixie_chat_messages:
        if getattr(msg, "bubble_id", "").startswith(LOGIN_BUBBLE_PREFIX):
            _fill_bubble(msg, content, cta)
            redraw_chat_areas()
            return

    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = f"{LOGIN_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
    msg.sender = "AGENT"
    msg.message_type = "AGENT"
    _fill_bubble(msg, content, cta)

    try:
        from .animation_manager import start_slide_redraw_burst
        start_slide_redraw_burst()
    except Exception:
        pass
    redraw_chat_areas()


def _fill_bubble(msg, content: str, cta: str) -> None:
    """Markdown content plus the cta's buttons (presentation only, no turn)."""
    msg.content = content
    msg.text = content
    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments

        set_markdown_segments(msg, parse_markdown_to_segments(content, streaming=False))
    except Exception as e:
        logger.debug(f"sign-in notice markdown parse skipped: {e}")

    msg.action_items.clear()
    for index, (label, value) in enumerate(notice_buttons(cta)):
        action = msg.action_items.add()
        action.label = iface_(label)
        action.value = value
        action.style = "PRIMARY" if index == 0 else "DEFAULT"
