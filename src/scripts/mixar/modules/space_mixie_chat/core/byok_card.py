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

One card per scene (`BUBBLE_PREFIX`): a repeat refusal refreshes it and
moves it to the end of the transcript, under the message it refused; every
fill and the dismissal bump the chat layout epoch so the native renderer
re-lays it out. The native hit targets are that cached layout, so a click can
name a card already gone (ignored) or land on a button that a fill just moved
under the pointer (ignored for `CLICK_GUARD_S` after each fill).
Nothing here logs or stores key material. Main thread only.
"""

import time
import uuid
from types import SimpleNamespace

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, n_, rpt_

from . import byok_notice, byok_resend
from .ui_utils import bump_layout_epoch, redraw_chat_areas

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

# A fill moves the buttons (Why unfolds a line, a refresh changes the text),
# and the second press of a double click would land on whatever slid under
# it — "Use Mixar credits instead" sits where Why was. Clicks this soon after
# a fill are dropped; a first read of a new card takes longer than this.
CLICK_GUARD_S = 0.5

# The card behind each bubble id (process-local; a transcript restored from
# disk has no card and its buttons fall back to the credential mirror).
_cards: dict = {}
# When each card was last filled (`_clock`), for the click guard.
_filled_at: dict = {}
_clock = time.monotonic
# A refused interjection's card, held while the turn it was sent into still
# streams (session id → card); `turn_settled` posts it.
_held: dict = {}


def is_card_action(value: str) -> bool:
    return isinstance(value, str) and value.startswith(ACTION_PREFIX)


def show(scene, card) -> None:
    """Post (or refresh) the card on ``scene``."""
    if scene is None or not hasattr(scene, 'mixie_chat_messages'):
        return
    if _streaming(scene):
        # A refused interjection: its turn still streams, and the card would
        # land between that turn's bubbles. It is posted when the turn
        # settles (`turn_settled`); the refused message stays remembered.
        _held[_session_key(scene)] = card
        return
    bubble = _find(scene)
    messages = scene.mixie_chat_messages
    if bubble is None:
        bubble = messages.add()
        bubble.bubble_id = f"{BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
        bubble.sender = 'AGENT'
        bubble.message_type = 'AGENT'
    else:
        bubble = _move_to_end(scene, bubble.bubble_id)
    _cards[bubble.bubble_id] = card
    _fill(scene, bubble, card.line, _actions_for(card))
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
    _held.pop(_session_key(scene), None)
    for index, item in enumerate(scene.mixie_chat_messages):
        if getattr(item, 'bubble_id', '').startswith(BUBBLE_PREFIX):
            _cards.pop(item.bubble_id, None)
            _filled_at.pop(item.bubble_id, None)
            scene.mixie_chat_messages.remove(index)
            # The resend adds its placeholder first, so the count is back
            # where it was: without the epoch the card's buttons keep drawing.
            bump_layout_epoch(scene)
            break
    redraw_chat_areas()


def turn_settled(scene) -> None:
    """``scene``'s turn stopped streaming or its run closed (called by
    `session.SessionManager`): post a card held for it and, once no turn is
    in flight anywhere, give a card stuck on "Couldn't resend yet" its line
    and buttons back. Never raises — the session's state change must land."""
    try:
        card = None if _streaming(scene) else _held.pop(_session_key(scene), None)
        if card is not None:
            show(scene, card)
        from mixar.modules.byok.ui.operators.byok_dialog_support import turn_in_flight
        if turn_in_flight(SimpleNamespace(scene=scene)):
            return
        import bpy
        blocked = rpt_(_RESEND_BLOCKED_LINE)
        for each in bpy.data.scenes:
            bubble = _find(each) if hasattr(each, 'mixie_chat_messages') else None
            if bubble is not None and bubble.text == blocked:
                card = (_cards.get(bubble.bubble_id)
                        or byok_notice.refusal_card({}, {"code": "byok_key_required"}))
                _fill(each, bubble, card.line, _actions_for(card))
                redraw_chat_areas()
    except Exception as exc:  # noqa: BLE001
        logger.debug("byok card turn-settled update skipped: %s", exc)


def handle_action(scene, bubble_id: str, value: str) -> bool:
    """A click on one of the card's buttons. True when it was one of ours."""
    if not is_card_action(value):
        return False
    bubble = _find(scene, bubble_id)
    if bubble is None:
        # A cached hit target of a card already dismissed: nothing to act on.
        return True
    if _clock() - _filled_at.get(bubble_id, float('-inf')) < CLICK_GUARD_S:
        logger.debug("byok card click ignored: the card was just re-laid out")
        return True
    card = _cards.get(bubble_id) or byok_notice.refusal_card({}, {"code": "byok_key_required"})
    session_id = getattr(scene, 'mixie_session_id', '') or ''
    if value == ACTION_WHY:
        # Idempotent: a click on a stale Why target (one dispatched before the
        # re-layout dropped the button) must not stack the line.
        why = f"\n\n{card.why_line}"
        text = bubble.text if bubble.text.endswith(why) else bubble.text + why
        _fill(scene, bubble, text, [a for a in _actions_for(card) if a[1] != ACTION_WHY])
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
    # A save resends on the new key; removing the account's key there (Remove
    # key / Disconnect) is "Use Mixar credits instead" done in the dialog —
    # it already applied the removal, so only the resend is left.
    key_prompt.request(card.provider, card.model, card.focus,
                       on_saved=lambda: _resend_or_explain(session_id),
                       on_removed=lambda: _resend_or_explain(session_id))
    if not _invoke_dialog():
        key_prompt.reset()
        if bubble is not None:
            _fill(scene, bubble, rpt_(_DIALOG_BUSY_LINE), _actions_for(card))
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
    from mixar.modules.byok.ui.operators.byok_dialog_support import turn_in_flight
    if turn_in_flight(SimpleNamespace(scene=scene)):
        # A turn (here or in another tab) runs on this key: removing it now
        # would land under that reply and send the next one on credits.
        if bubble is not None:
            _fill(scene, bubble, rpt_(_RESEND_BLOCKED_LINE), _actions_for(card))
            redraw_chat_areas()
        return
    if bubble is not None:
        _fill(scene, bubble, rpt_(_SWITCHING_LINE), [])
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
    _fill(scene, bubble, line, _actions_for(card))
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


def _session_key(scene) -> str:
    return getattr(scene, 'mixie_session_id', '') or getattr(scene, 'name', '')


def _streaming(scene) -> bool:
    """The scene's turn is streaming (BUSY): only an interjection is refused
    then — a normal send's refusal restored the state before reaching here."""
    from ..constants import SessionState
    from .session import get_session_manager
    return get_session_manager().get_state(scene) == SessionState.BUSY


def _find(scene, bubble_id=None):
    for item in scene.mixie_chat_messages:
        current = getattr(item, 'bubble_id', '')
        if current == bubble_id or (bubble_id is None and current.startswith(BUBBLE_PREFIX)):
            return item
    return None


def _move_to_end(scene, bubble_id: str):
    """A repeat refusal brings the card under the message it refused, so it
    never stays scrolled away above it. Returns the card re-read after the
    move: a bpy collection reference goes stale when the collection moves."""
    messages = scene.mixie_chat_messages
    last = len(messages) - 1
    for index, item in enumerate(messages):
        if getattr(item, 'bubble_id', '') == bubble_id:
            if index != last:
                messages.move(index, last)
            break
    return messages[last]


def _fill(scene, bubble, content: str, actions) -> None:
    """Content + markdown segments for the native renderer + the buttons.
    Presentation only — the actions slot no longer infers a paused turn
    from the presence of buttons. Bumps the layout epoch: the native layout
    cache keys on the message count, so a refresh in place (or a move to
    the end) with an unchanged count would otherwise draw stale rows."""
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
    _filled_at[bubble.bubble_id] = _clock()
    bump_layout_epoch(scene)
