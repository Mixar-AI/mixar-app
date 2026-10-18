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

The notice answers its own buttons: Sign in reads "finish in your browser"
until the sign-in lands, then the notice settles to "You're signed in"
(no buttons); a failed sign-in says so; a saved key settles it too. Before
this a click changed nothing on screen and the user kept pressing Sign in
long after it had worked. A settled notice resends the refused message
(`byok_resend`, remembered by the transport) once the socket is back for the
new identity, and goes away; with nothing to resend, or no socket in time,
it asks for the send instead.
"""

import time
import uuid

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.auth.core.guest import CTA_FIX_BYOK, CTA_LOGIN, CTA_LOGIN_OR_BYOK
from mixar.modules.common.i18n import iface_, n_, rpt_

from .ui_utils import bump_layout_epoch, redraw_chat_areas

logger = get_logger(__name__)

# Stable bubble-id prefix: repeated refusals refresh one notice, never stack.
LOGIN_BUBBLE_PREFIX = "login-required-"

# Action-button ``value`` sentinels, handled client-side by chat_special_ops.
SIGN_IN_CHAT_ACTION = "__mixar_sign_in__"
BYOK_DIALOG_CHAT_ACTION = "__mixar_open_byok_dialog__"

_CONTENT_MAXLEN = 4096

#: Settled states: (title, body). Every one asks for the send again — the
#: refused message never reached the agent.
_SEND_AGAIN = n_("Send your message again to continue.")
_SIGNED_IN = (n_("You're signed in"), _SEND_AGAIN)
_GUEST_READY = (n_("Guest session started"), _SEND_AGAIN)
_KEY_SAVED = (n_("Your key is saved"), _SEND_AGAIN)
_SENDING = n_("Sending your message…")
_PENDING_SIGN_IN = n_("Finish signing in in your browser. This message updates when you're back.")
_SIGN_IN_FAILED = n_("Sign-in didn't finish. Try again.")

# A sign-in reconnects the socket as the account; the resend waits for it.
_RESEND_WAIT_S = 20.0
_RESEND_POLL_S = 0.5

# Notices posted by this process: bubble id -> {"cta", "guest": a fresh guest
# session settles it (the app had no session at all), "pending": a sign-in
# from its button is running}. A transcript restored from disk is not here,
# so a sign-in never rewrites an old notice.
_notices: dict = {}

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


def add_login_required_chat_message(scene=None, cta: str = CTA_LOGIN, body: str = "",
                                    *, resolves_on_guest: bool = False) -> None:
    """Add (or refresh) the sign-in notice bubble for ``cta``.

    ``body`` is the backend's already-worded message when it sent one; the
    title is the client's, so every cta reads the same whatever the server
    text said. ``resolves_on_guest``: the app had no session at all, so a
    fresh guest session settles the notice as well as a sign-in.
    """
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene or not hasattr(scene, "mixie_chat_messages"):
        logger.warning("Cannot add sign-in chat message - scene missing")
        return

    title, default_body = _COPY.get(cta) or _COPY[CTA_LOGIN]
    content = f"**{rpt_(title)}**\n\n{(body or rpt_(default_body)).strip()}"[:_CONTENT_MAXLEN]

    msg = _find(scene)
    if msg is not None:
        _fill_bubble(msg, content, cta)
        _notices[msg.bubble_id] = {"cta": cta, "guest": resolves_on_guest, "pending": False}
        redraw_chat_areas()
        return

    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = f"{LOGIN_BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
    msg.sender = "AGENT"
    msg.message_type = "AGENT"
    _fill_bubble(msg, content, cta)
    _notices[msg.bubble_id] = {"cta": cta, "guest": resolves_on_guest, "pending": False}

    try:
        from .animation_manager import start_slide_redraw_burst
        start_slide_redraw_burst()
    except Exception:
        pass
    redraw_chat_areas()


def sign_in_clicked(scene):
    """The notice's Sign in button: an account already signed in settles the
    notice at once; otherwise the notice waits on the browser sign-in."""
    from mixar.modules.common.utils import topbar_layout

    if topbar_layout.account_signed_in(bpy.context.window_manager):
        session_ready(is_guest=False)
        return {'FINISHED'}
    msg = _find(scene) if scene is not None else None
    notice = _notices.get(getattr(msg, "bubble_id", ""))
    if notice is not None:
        notice["pending"] = True
        _fill_bubble(msg, _content(msg, rpt_(_PENDING_SIGN_IN)), notice["cta"])
        redraw_chat_areas()
    return bpy.ops.mixie_chat.login()


def session_ready(is_guest: bool) -> None:
    """A sign-in (or a fresh guest session) landed: settle every live notice
    it answers. A guest session answers only a no-session notice."""
    _settle_all(lambda notice: not is_guest or notice["guest"],
                _GUEST_READY if is_guest else _SIGNED_IN)


def key_saved() -> None:
    """AI Provider Settings saved a key: settle every notice offering one."""
    _settle_all(lambda notice: any(value == BYOK_DIALOG_CHAT_ACTION
                                   for _label, value in notice_buttons(notice["cta"])),
                _KEY_SAVED)


def sign_in_failed() -> None:
    """A sign-in started from a notice failed: say so, keep the buttons."""
    for scene, msg, notice in _live():
        if notice["pending"]:
            notice["pending"] = False
            _fill_bubble(msg, _content(msg, rpt_(_SIGN_IN_FAILED)), notice["cta"])
    redraw_chat_areas()


def _settle_all(answers, state) -> None:
    title, body = state
    for scene, msg, notice in list(_live()):
        if answers(notice):
            _notices.pop(msg.bubble_id, None)
            _settle(scene, msg, title, body)
    redraw_chat_areas()


def _settle(scene, msg, title: str, body: str) -> None:
    """Resend the message the refusal stopped, or ask for the send."""
    from . import byok_resend

    session_id = getattr(scene, "mixie_session_id", "") or ""
    if not session_id or byok_resend.pending(session_id) is None:
        _fill_bubble(msg, f"**{rpt_(title)}**\n\n{rpt_(body)}", None)
        return
    _fill_bubble(msg, f"**{rpt_(title)}**\n\n{rpt_(_SENDING)}", None)
    bubble_id, deadline = msg.bubble_id, time.monotonic() + _RESEND_WAIT_S

    def _try():
        # Session id and bubble id only: the transcript can change underneath.
        if _connected() and byok_resend.resend(session_id):
            _remove(byok_resend._scene_for(session_id), bubble_id)
            return None
        if time.monotonic() < deadline:
            return _RESEND_POLL_S
        target = byok_resend._scene_for(session_id)
        bubble = _find(target) if target is not None else None
        if bubble is not None and bubble.bubble_id == bubble_id:
            _fill_bubble(bubble, f"**{rpt_(title)}**\n\n{rpt_(body)}", None)
            redraw_chat_areas()
        return None

    bpy.app.timers.register(_try, first_interval=0.0)


def _connected() -> bool:
    """The socket is up with a connection id: a send can go out."""
    from .connection_manager import get_connection_manager
    from .jsonrpc_client import get_jsonrpc_client

    client = get_jsonrpc_client()
    return bool(get_connection_manager().is_connected and client and client.connection_id)


def _remove(scene, bubble_id: str) -> None:
    """Drop the notice: the message is on its way again."""
    messages = getattr(scene, "mixie_chat_messages", None)
    if messages is None:
        return
    for index, msg in enumerate(messages):
        if getattr(msg, "bubble_id", "") == bubble_id:
            messages.remove(index)
            break
    # The C++ layout cache rebuilds on a message-COUNT change only: a bubble
    # added in this one's place (the key card a refused resend shows) kept
    # the notice's cached buttons.
    bump_layout_epoch(scene)
    redraw_chat_areas()


def _live():
    """``(scene, bubble, notice)`` for every notice this process posted."""
    for scene in getattr(bpy.data, "scenes", ()):
        msg = _find(scene)
        notice = _notices.get(getattr(msg, "bubble_id", ""))
        if notice is not None:
            yield scene, msg, notice


def _find(scene):
    for msg in getattr(scene, "mixie_chat_messages", ()):
        if getattr(msg, "bubble_id", "").startswith(LOGIN_BUBBLE_PREFIX):
            return msg
    return None


def _content(msg, body: str) -> str:
    """The notice's title line with a new body."""
    title = (msg.content or "").split("\n\n", 1)[0]
    return f"{title}\n\n{body}"[:_CONTENT_MAXLEN]


def _fill_bubble(msg, content: str, cta) -> None:
    """Markdown content plus the cta's buttons (presentation only, no turn);
    ``cta`` None draws no buttons (a settled notice). The bubble's height
    changes in place, so the layout cache is bumped."""
    msg.content = content
    msg.text = content
    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments

        set_markdown_segments(msg, parse_markdown_to_segments(content, streaming=False))
    except Exception as e:
        logger.debug(f"sign-in notice markdown parse skipped: {e}")

    msg.action_items.clear()
    for index, (label, value) in enumerate(notice_buttons(cta) if cta else ()):
        action = msg.action_items.add()
        action.label = iface_(label)
        action.value = value
        action.style = "PRIMARY" if index == 0 else "DEFAULT"
    scene = getattr(msg, "id_data", None)  # the Scene owning the transcript
    if scene is not None:
        bump_layout_epoch(scene)
