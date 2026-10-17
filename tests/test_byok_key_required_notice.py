# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A turn refused over the user's own key shows ONE desktop-owned card line.

The server answers a keyless command under active BYOK with a 409
``byok_key_required`` (now naming ``provider`` and ``model``); the client's
own Codex refusals share the path. The card line is provider-specific,
names no device, account or BYOK, never shows the server's message (the
fallback for old builds), and offers two actions. Before the cold-start
credential fetch has landed nothing is shown: the message is resent once the
fetch lands, and only a second refusal shows the card.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import codex_auth, credential_state, key_prompt  # noqa: E402
from mixar.modules.space_mixie_chat.core import byok_card, byok_notice, byok_resend  # noqa: E402

OLD_SERVER_MESSAGE = ("Your own API key is set up for this account but this device did not send it. "
                      "Update Mixar if an update is available, then enter your key in AI Provider "
                      "Settings on this device — or turn BYOK off.")
BANNED_WORDS = ("device", "account", "BYOK", "AI Provider Settings")


class _Collection(list):
    def add(self):
        item = SimpleNamespace(bubble_id="", sender="", message_type="", text="", content="",
                               metadata="", action_items=_Collection())
        self.append(item)
        return item

    def remove(self, index):
        del self[index]

    def move(self, src, dst):
        self.insert(dst, self.pop(src))


def _scene():
    return SimpleNamespace(name="Scene", mixie_session_id="sess-1", mixie_chat_messages=_Collection())


def _loaded(monkeypatch, provider="anthropic"):
    monkeypatch.setattr(credential_state, "snapshot", lambda: {
        "byok_state_loaded": True, "byok_is_active": True, "byok_current_provider": provider})


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(byok_card, "redraw_chat_areas", lambda: None)
    byok_card._cards.clear()
    byok_resend._records.clear()
    byok_resend._auto_ids.clear()
    key_prompt.reset()
    yield
    byok_card._cards.clear()
    byok_resend._records.clear()
    byok_resend._auto_ids.clear()
    key_prompt.reset()


def _card_bubbles(scene):
    return [m for m in scene.mixie_chat_messages if m.bubble_id.startswith(byok_card.BUBBLE_PREFIX)]


def _409(provider, model="m", **extra):
    data = {"status_code": 409, "code": "byok_key_required", "provider": provider, "model": model,
            "message": OLD_SERVER_MESSAGE, **extra}
    return {"message": OLD_SERVER_MESSAGE, "data": data}, data


# ---------------------------------------------------------------------------
# The line per provider
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider, line, button, focus", [
    ("openai", "Enter your OpenAI API key to continue", "Enter key", key_prompt.FOCUS_KEY),
    ("anthropic", "Enter your Anthropic API key to continue", "Enter key", key_prompt.FOCUS_KEY),
    ("gemini", "Enter your Gemini API key to continue", "Enter key", key_prompt.FOCUS_KEY),
    ("openrouter", "Enter your OpenRouter API key to continue", "Enter key", key_prompt.FOCUS_KEY),
    ("xai", "Enter your Xai API key to continue", "Enter key", key_prompt.FOCUS_KEY),
    ("codex", "Link your ChatGPT sign-in to continue", "Link sign-in", key_prompt.FOCUS_CODEX_PATH),
    ("local", "Enter your local model's token to continue", "Enter token", key_prompt.FOCUS_LOCAL_KEY),
])
def test_the_card_line_is_one_provider_specific_sentence(provider, line, button, focus):
    result, data = _409(provider, "model-x")
    card = byok_notice.refusal_card(result, data)
    assert card.line == line
    assert card.primary_label == button and card.primary_action == byok_notice.ACTION_ENTER
    assert card.credits_label == "Use Mixar credits instead"
    assert (card.provider, card.model, card.focus) == (provider, "model-x", focus)
    for word in BANNED_WORDS:
        assert word not in card.line and word not in card.primary_label
    assert OLD_SERVER_MESSAGE not in card.line


def test_the_409_fields_are_read_from_the_socket_data_and_the_receipt_top_level():
    socket = {"status_code": 409, "code": "byok_key_required", "provider": "OpenAI", "model": "gpt"}
    card = byok_notice.refusal_card({"message": "m", "data": socket}, socket)
    assert (card.provider, card.model) == ("openai", "gpt")
    receipt = {"ok": False, "status_code": 409, "code": "byok_key_required", "provider": "anthropic",
               "model": "claude", "message": "m"}
    card = byok_notice.refusal_card(receipt, {})
    assert (card.provider, card.model) == ("anthropic", "claude")
    assert card.line == "Enter your Anthropic API key to continue"


def test_a_409_without_provider_falls_back_to_the_credential_mirror(monkeypatch):
    monkeypatch.setattr(credential_state, "snapshot", lambda: {
        "byok_state_loaded": True, "byok_is_active": True,
        "byok_current_provider": "openrouter", "byok_current_model": "anthropic/claude"})
    data = {"status_code": 409, "code": "byok_key_required", "message": OLD_SERVER_MESSAGE}
    card = byok_notice.refusal_card({"message": OLD_SERVER_MESSAGE, "data": data}, data)
    assert card.line == "Enter your OpenRouter API key to continue"
    assert (card.provider, card.model) == ("openrouter", "anthropic/claude")


def test_a_409_without_the_byok_code_is_not_byok_and_other_errors_are_not_either(monkeypatch):
    touched = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", touched.append)
    monkeypatch.setattr(credential_state, "refresh", lambda: touched.append("refresh"))
    assert byok_notice.refusal_card({"message": "busy"}, {"status_code": 409}) is None
    assert byok_notice.present_refusal({"message": "busy"}, {"status_code": 409}, _scene()) is False
    assert byok_notice.refusal_card({"message": "boom"}, {"status_code": 500}) is None
    assert byok_notice.refusal_card({"message": "credits"}, {"status_code": 402}) is None
    assert byok_notice.byok_error_code({"code": -32020}, {"code": "other"}) == ""
    assert touched == []


# ---------------------------------------------------------------------------
# Presenting it
# ---------------------------------------------------------------------------

def test_a_loaded_409_posts_the_card_and_re_derives_the_pill_from_the_store(monkeypatch):
    """The settings card / pill derivation is unchanged: `check_presence_async`
    for the account's provider, never a blind flip."""
    from mixar.modules.byok.core import key_store

    _loaded(monkeypatch, "openai")
    checks = []
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, cb: checks.append((provider, cb)))
    scene = _scene()
    result, data = _409("openai")
    assert byok_notice.present_refusal(result, data, scene) is True
    (bubble,) = _card_bubbles(scene)
    assert bubble.text == "Enter your OpenAI API key to continue"
    assert "did not send" not in bubble.text and OLD_SERVER_MESSAGE not in bubble.text
    assert [(a.label, a.value, a.style) for a in bubble.action_items] == [
        ("Enter key", byok_card.ACTION_ENTER, "PRIMARY"),
        ("Use Mixar credits instead", byok_card.ACTION_USE_CREDITS, "DEFAULT"),
        ("Why am I seeing this?", byok_card.ACTION_WHY, "DEFAULT"),
    ]
    assert checks == [("openai", credential_state.set_device_key_missing)]
    # A repeat refusal refreshes the one card instead of stacking another.
    byok_notice.present_refusal(*_409("anthropic"), scene)
    (bubble,) = _card_bubbles(scene)
    assert bubble.text == "Enter your Anthropic API key to continue"


def test_why_am_i_seeing_this_unfolds_one_line_and_names_no_device(monkeypatch):
    from mixar.modules.byok.core import key_store

    _loaded(monkeypatch, "openai")
    monkeypatch.setattr(key_store, "check_presence_async", lambda *a: None)
    scene = _scene()
    byok_notice.present_refusal(*_409("openai"), scene)
    (bubble,) = _card_bubbles(scene)
    assert byok_card.handle_action(scene, bubble.bubble_id, byok_card.ACTION_WHY) is True
    assert bubble.text.splitlines()[0] == "Enter your OpenAI API key to continue"
    assert bubble.text.endswith("Mixar never keeps your key on its servers. "
                                "It stays only on the computer where you enter it.")
    assert [a.value for a in bubble.action_items] == [byok_card.ACTION_ENTER, byok_card.ACTION_USE_CREDITS]


# ---------------------------------------------------------------------------
# Cold start: silent, refresh, resend once
# ---------------------------------------------------------------------------

@pytest.fixture
def cold(monkeypatch):
    monkeypatch.setattr(credential_state, "snapshot", lambda: {"byok_state_loaded": False, "byok_is_active": False})
    hooks, refreshes, resends, flips = [], [], [], []
    monkeypatch.setattr(credential_state, "on_next_fetch", hooks.append)
    monkeypatch.setattr(credential_state, "refresh", lambda: refreshes.append(True))
    monkeypatch.setattr(credential_state, "set_device_key_missing", flips.append)
    scene = _scene()
    monkeypatch.setattr(byok_resend, "_scene_for", lambda sid: scene if sid == "sess-1" else None)

    def _resend(sid, automatic=False):
        resends.append((sid, automatic))
        return True

    monkeypatch.setattr(byok_resend, "resend", _resend)
    byok_resend.remember("sess-1", "cmd-1", "chat", {"session_id": "sess-1", "message": "hi"}, False)
    return SimpleNamespace(scene=scene, hooks=hooks, refreshes=refreshes, resends=resends, flips=flips)


def test_a_409_before_the_first_fetch_shows_nothing_and_resends_when_the_fetch_lands(cold):
    assert byok_notice.present_refusal(*_409("openai"), cold.scene) is True
    assert _card_bubbles(cold.scene) == [] and cold.refreshes == [True] and cold.flips == []
    (hook,) = cold.hooks
    hook(True)
    assert cold.resends == [("sess-1", True)]
    assert _card_bubbles(cold.scene) == []


def test_the_cold_start_resend_is_one_shot_a_second_refusal_shows_the_card(cold, monkeypatch):
    byok_notice.present_refusal(*_409("openai"), cold.scene)
    cold.hooks.pop()(True)
    # The automatic resend was refused too: the record carries `auto_resent`.
    byok_resend._auto_ids.add("cmd-2")
    byok_resend.remember("sess-1", "cmd-2", "chat", {"session_id": "sess-1"}, False)
    assert byok_resend.pending("sess-1").auto_resent is True
    refreshes_before = len(cold.refreshes)
    byok_notice.present_refusal(*_409("openai"), cold.scene)
    (bubble,) = _card_bubbles(cold.scene)
    assert bubble.text == "Enter your OpenAI API key to continue"
    assert cold.hooks == [] and len(cold.resends) == 1
    # Still unloaded, so the mirror is refreshed (never flipped) as before.
    assert len(cold.refreshes) == refreshes_before + 1 and cold.flips == []


def test_a_failed_cold_start_fetch_shows_the_card_instead_of_losing_the_message(cold):
    byok_notice.present_refusal(*_409("openai"), cold.scene)
    cold.hooks.pop()(False)
    assert cold.resends == []
    (bubble,) = _card_bubbles(cold.scene)
    assert bubble.text == "Enter your OpenAI API key to continue"


# ---------------------------------------------------------------------------
# The Codex family
# ---------------------------------------------------------------------------

def test_codex_expired_asks_for_a_new_sign_in_with_the_short_reason_the_code_carries():
    expired = {"code": "byok_codex_expired"}
    card = byok_notice.refusal_card({"message": codex_auth.MSG_SIGN_IN_EXPIRED}, expired)
    assert card.line == "Sign in to Codex again to continue"
    assert card.primary_label == "Sign in to Codex" and card.primary_action == byok_notice.ACTION_ENTER
    assert (card.provider, card.focus) == ("codex", key_prompt.FOCUS_CODEX_PATH)
    card = byok_notice.refusal_card({"message": codex_auth.MSG_FILE_MISSING}, expired)
    assert card.line == "Sign in to Codex again to continue — no Codex sign-in was found"
    card = byok_notice.refusal_card({"message": codex_auth.MSG_FILE_UNREADABLE}, expired)
    assert card.line == "Sign in to Codex again to continue — the sign-in file could not be read"
    assert "device" not in card.line and "`" not in card.line


def test_codex_refresh_failures_are_transient_with_try_again_except_an_unwritable_file():
    failed = {"code": "byok_codex_refresh_failed"}
    card = byok_notice.refusal_card({"message": "NET-7"}, failed)
    assert card.line == "Couldn't renew your Codex sign-in — check your connection"
    assert card.primary_label == "Try again" and card.primary_action == byok_notice.ACTION_RESEND
    card = byok_notice.refusal_card({"message": codex_auth.MSG_FILE_NOT_WRITABLE}, failed)
    assert card.line.startswith("Your Codex sign-in file is not writable")
    assert card.primary_label == "Sign in to Codex" and card.focus == key_prompt.FOCUS_CODEX_PATH


def test_codex_refusals_post_the_card_without_touching_the_pill(monkeypatch):
    touched = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", touched.append)
    monkeypatch.setattr(credential_state, "refresh", lambda: touched.append("refresh"))
    scene = _scene()
    assert byok_notice.present_refusal({"message": "NET-7"}, {"code": "byok_codex_refresh_failed"}, scene)
    (bubble,) = _card_bubbles(scene)
    assert bubble.action_items[0].label == "Try again" and bubble.action_items[0].value == byok_card.ACTION_RESEND
    assert touched == []


# ---------------------------------------------------------------------------
# Wiring pins
# ---------------------------------------------------------------------------

def test_queue_processor_routes_byok_refusals_before_the_credit_branch_and_never_resends():
    src = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "queue_processor.py").read_text(encoding="utf-8")
    body = src[src.index("def handle_command_error("):src.index("def _handle_agent_error_internal(")]
    assert body.index("present_refusal(") < body.index("is_credits_exhausted_error(status, message)")
    # The card owns the resend (new command id); the error path never does.
    assert "self._end_refused_turn(scene)" in body
    for resend in ("start_stream(", "start_input_stream(", "send_user_message(", "resend("):
        assert resend not in body
    # The server's prose is never rendered on a current desktop.
    assert "byok_error_message" not in src


def test_the_transport_remembers_a_refused_command_for_the_card():
    src = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "turn_transport.py").read_text(encoding="utf-8")
    settled = src[src.index("def settled("):src.index("turn_events.expect(scene, command_id, settled)")]
    assert "byok_error_code(result, result.get('data') or {})" in settled
    # The remembered payload keeps the images themselves (not upload refs).
    assert "byok_resend.remember(payload['session_id'], command_id, method, remembered, joining)" in settled
    assert settled.index("byok_resend.remember(") < settled.index("processor.handle_command_error(result, target)")


def test_nothing_on_this_path_logs_or_keeps_key_material():
    byok_resend.remember("s", "c", "chat", {"session_id": "s", "byok_key": "sk-secret",
                                            "byok_account_id": "acct", "message": "hi"}, False)
    assert byok_resend.pending("s").payload == {"session_id": "s", "message": "hi"}
    core = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core"
    for name in ("byok_notice.py", "byok_card.py", "byok_resend.py"):
        for line in (core / name).read_text(encoding="utf-8").splitlines():
            if "logger." in line:
                assert "payload" not in line and "byok_key" not in line and "api_key" not in line, (name, line)


def test_a_refreshed_card_moves_under_the_message_it_refuses(monkeypatch):
    """A second refusal in a chat that already holds a key card (a plaintext /
    sealing refusal, a second key-needed) must show at the bottom, under the
    refused message — not refresh the old card six bubbles up (QA 2026-10-17,
    F8: the bottom only read "could not be delivered")."""
    _loaded(monkeypatch)
    scene = _scene()
    first = byok_notice.refusal_card(*_409("openai"))
    byok_card.show(scene, first)
    for sender, text in (("USER", "pong?"), ("AGENT", "pong"), ("USER", "plaintext?")):
        item = scene.mixie_chat_messages.add()
        item.sender, item.bubble_id, item.text = sender, f"b-{text}", text
    unsealed = {"code": "byok_key_unsealed", "status_code": 400,
                "message": "The key for this request was not sealed for Mixar. Update Mixar and try again."}
    byok_card.show(scene, byok_notice.refusal_card({"message": unsealed["message"], "data": unsealed}, unsealed))
    cards = _card_bubbles(scene)
    assert len(cards) == 1                              # still one card
    assert scene.mixie_chat_messages[-1] is cards[0]    # now the last message
    assert "not sealed" in cards[0].content or "not sealed" in cards[0].text
    assert [m.text for m in scene.mixie_chat_messages[:-1]] == ["pong?", "pong", "plaintext?"]
