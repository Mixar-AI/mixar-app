# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The key-missing card in the chat: one line, two actions, a quiet "why".

A client-originated AGENT bubble built like the credits notice
(`credits_notice.py`): markdown segments for the native renderer plus
``action_items`` the transcript draws as buttons, in the island, the pill
and every chat surface alike. Clicks reach
`MIXIE_CHAT_OT_select_slot_action`, which hands every ``byok_card:`` value
to `handle_action` before anything goes to the backend.

Actions:

- the primary — **Enter key** / **Link sign-in** / **Enter token** / **Sign
  in to Codex** — arms `byok/core/key_prompt` (provider, model, the field
  to focus, "resend on save") and opens AI Provider Settings; **Try again**
  resends at once;
- **Use Mixar credits instead** removes the key (`byok_client.delete_credentials`,
  worker thread) and, on the 200, resends the message on platform credits;
- **Why am I seeing this?** unfolds one line under the card.

One card per scene (`BUBBLE_PREFIX`): a repeat refusal refreshes it in
place. Nothing here logs or stores key material. Main thread only.
"""

import uuid

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, n_, rpt_

from . import byok_notice, byok_resend
from .ui_utils import redraw_chat_areas

logger = get_logger(__name__)

BUBBLE_PREFIX = "byok-key-"
ACTION_PREFIX = "byok_card:"
ACTION_ENTER = ACTION_PREFIX + "enter"
ACTION_RESEND = ACTION_PREFIX + "resend"
ACTION_USE_CREDITS = ACTION_PREFIX + "use_credits"
ACTION_WHY = ACTION_PREFIX + "why"

_WHY_LABEL = n_("Why am I seeing this?")
_SWITCHING_LINE = n_("Switching to Mixar credits…")
_SWITCH_FAILED_LINE = n_("Couldn't switch to Mixar credits — try again")
_RESEND_BLOCKED_LINE = n_("Couldn't resend yet — wait for the current reply to finish, then try again")
_DIALOG_BUSY_LINE = n_("AI Provider Settings is already open — enter your key there")

# The card behind each bubble id (process-local; a transcript restored from
# disk has no card and its buttons fall back to the credential mirror).
_cards: dict = {}


def is_card_action(value: str) -> bool:
    return isinstance(value, str) and value.startswith(ACTION_PREFIX)


def show(scene, card) -> None:
    """Post (or refresh) the card on ``scene``."""
    if scene is None or not hasattr(scene, 'mixie_chat_messages'):
        return
    bubble = _find(scene)
    messages = scene.mixie_chat_messages
    if bubble is not None and messages[-1].bubble_id != bubble.bubble_id:
        # An earlier card further up the chat: the refusal belongs under the
        # message it refuses, where the user is looking — move it down.
        index = next(i for i, item in enumerate(messages) if item.bubble_id == bubble.bubble_id)
        messages.move(index, len(messages) - 1)
        bubble = messages[-1]
    if bubble is None:
        bubble = messages.add()
        bubble.bubble_id = f"{BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
        bubble.sender = 'AGENT'
        bubble.message_type = 'AGENT'
    _cards[bubble.bubble_id] = card
    _fill(bubble, card.line, _actions_for(card))
    try:
        from .animation_manager import start_slide_redraw_burst
        start_slide_redraw_burst()
    except Exception:  # noqa: BLE001
        pass
    redraw_chat_areas()


def dismiss(scene) -> None:
    """Drop the card (the message is on its way again)."""
    if scene is None or not hasattr(scene, 'mixie_chat_messages'):
        return
    for index, item in enumerate(scene.mixie_chat_messages):
        if getattr(item, 'bubble_id', '').startswith(BUBBLE_PREFIX):
            _cards.pop(item.bubble_id, None)
            scene.mixie_chat_messages.remove(index)
            break
    redraw_chat_areas()


def handle_action(scene, bubble_id: str, value: str) -> bool:
    """A click on one of the card's buttons. True when it was one of ours."""
    if not is_card_action(value):
        return False
    bubble = _find(scene, bubble_id)
    card = _cards.get(bubble_id) or byok_notice.refusal_card({}, {"code": "byok_key_required"})
    session_id = getattr(scene, 'mixie_session_id', '') or ''
    if value == ACTION_WHY and bubble is not None:
        _fill(bubble, f"{bubble.text}\n\n{card.why_line}",
              [a for a in _actions_for(card) if a[1] != ACTION_WHY])
        redraw_chat_areas()
    elif value == ACTION_RESEND:
        _resend_or_explain(session_id)
    elif value == ACTION_ENTER:
        _open_settings(scene, bubble, card, session_id)
    elif value == ACTION_USE_CREDITS:
        _use_credits(scene, bubble, card, session_id)
    return True


# ---------------------------------------------------------------------------
# Actions. Callbacks that outlive the click carry the SESSION ID only and
# re-resolve the scene and bubble: a save closes the bubble windows and a
# PropertyGroup reference taken before that can go stale.
# ---------------------------------------------------------------------------

def _open_settings(scene, bubble, card, session_id) -> None:
    from mixar.modules.byok.core import key_prompt
    key_prompt.request(card.provider, card.model, card.focus,
                       on_saved=lambda: _resend_or_explain(session_id))
    if not _invoke_dialog():
        key_prompt.reset()
        if bubble is not None:
            _fill(bubble, rpt_(_DIALOG_BUSY_LINE), _actions_for(card))
            redraw_chat_areas()


def _invoke_dialog() -> bool:
    try:
        import bpy
        result = bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not open AI Provider Settings from the chat card: %s", exc)
        return False
    return result != {'CANCELLED'}


def _resend_or_explain(session_id: str) -> None:
    """Resend the refused message; failing that, say so on the card."""
    scene = byok_resend._scene_for(session_id)
    if scene is None:
        return
    if byok_resend.resend(session_id):
        dismiss(scene)
        return
    _refresh_line(scene, rpt_(_RESEND_BLOCKED_LINE))


def _use_credits(scene, bubble, card, session_id) -> None:
    """Remove the account's key (worker thread), then resend on credits."""
    from mixar.modules.byok.core import byok_client
    if bubble is not None:
        _fill(bubble, rpt_(_SWITCHING_LINE), [])
        redraw_chat_areas()

    def _done(success: bool, removed_count: int, err):
        if success:
            _apply_removed(removed_count)
            _resend_or_explain(session_id)
            return
        logger.warning("BYOK removal from the chat card failed: %s", err)
        target = byok_resend._scene_for(session_id)
        if target is not None:
            _refresh_line(target, rpt_(_SWITCH_FAILED_LINE))

    byok_client.delete_credentials(on_done=_done)


def _refresh_line(scene, line: str) -> None:
    """Replace the card's line, keeping its buttons."""
    bubble = _find(scene)
    if bubble is None:
        return
    card = _cards.get(bubble.bubble_id) or byok_notice.refusal_card({}, {"code": "byok_key_required"})
    _fill(bubble, line, _actions_for(card))
    redraw_chat_areas()


def _apply_removed(removed_count: int) -> None:
    """The DELETE landed: the mirror reads inactive and LOADED (the next
    turn goes out keyless on purpose), the island picker refetches the
    hosted pick, a managed local runtime is torn down."""
    from mixar.modules.byok.core import credential_state, preference_state
    from mixar.modules.byok.core.local_switch import deregister_local_if_switched_away
    credential_state.clear(loaded=True)
    preference_state.refresh()
    logger.info("BYOK removed from the chat card: %d row(s) deleted", removed_count)
    deregister_local_if_switched_away(None)


# ---------------------------------------------------------------------------
# Bubble helpers
# ---------------------------------------------------------------------------

def _actions_for(card):
    return [
        (card.primary_label, ACTION_ENTER if card.primary_action == byok_notice.ACTION_ENTER
         else ACTION_RESEND, 'PRIMARY'),
        (card.credits_label, ACTION_USE_CREDITS, 'DEFAULT'),
        (iface_(_WHY_LABEL), ACTION_WHY, 'DEFAULT'),
    ]


def _find(scene, bubble_id=None):
    for item in scene.mixie_chat_messages:
        current = getattr(item, 'bubble_id', '')
        if current == bubble_id or (bubble_id is None and current.startswith(BUBBLE_PREFIX)):
            return item
    return None


def _fill(bubble, content: str, actions) -> None:
    """Content + markdown segments for the native renderer + the buttons.
    Presentation only — the actions slot no longer infers a paused turn
    from the presence of buttons."""
    bubble.content = content
    bubble.text = content
    try:
        from .markdown_parser import parse_markdown_to_segments
        from .message_helpers import set_markdown_segments
        set_markdown_segments(bubble, parse_markdown_to_segments(content, streaming=False))
    except Exception as exc:  # noqa: BLE001
        logger.debug("byok card markdown parse skipped: %s", exc)
    bubble.action_items.clear()
    for label, value, style in actions:
        action = bubble.action_items.add()
        action.label = label
        action.value = value
        action.style = style
