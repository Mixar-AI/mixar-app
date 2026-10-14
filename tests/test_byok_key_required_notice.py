# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A turn refused over the user's own key points at AI Provider Settings.

The server answers a keyless command under active BYOK with a 409
``byok_key_required``; the client's own Codex refusals share the path. Both
show the message plus the settings pointer, flip the device-key state, and
never retry.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import credential_state
from mixar.modules.space_mixie_chat.core import byok_notice


def _loaded(monkeypatch, provider="anthropic"):
    monkeypatch.setattr(credential_state, "snapshot", lambda: {
        "byok_state_loaded": True, "byok_is_active": True, "byok_current_provider": provider})


def test_server_409_over_the_socket_is_recognised_from_the_error_data(monkeypatch):
    """The card is re-derived from the key store for the account's provider,
    never flipped blindly."""
    from mixar.modules.byok.core import key_store

    _loaded(monkeypatch, "openai")
    checks = []
    monkeypatch.setattr(key_store, "check_presence_async", lambda provider, cb: checks.append((provider, cb)))
    data = {"status_code": 409, "code": "byok_key_required", "message": "Send your key."}
    text = byok_notice.byok_error_message({"message": "Send your key.", "data": data}, data, 409)
    assert text.startswith("Send your key.")
    assert "AI Provider Settings" in text
    assert checks == [("openai", credential_state.set_device_key_missing)]


def test_a_409_before_the_first_fetch_refreshes_the_mirror_instead(monkeypatch):
    """Cold start: the turn went out keyless because the mirror still read
    "inactive"; the fetch derives the real card state when it lands."""
    from mixar.modules.byok.core import key_store

    monkeypatch.setattr(credential_state, "snapshot", lambda: {"byok_state_loaded": False, "byok_is_active": False})
    refreshes, flips = [], []
    monkeypatch.setattr(credential_state, "refresh", lambda: refreshes.append(True))
    monkeypatch.setattr(credential_state, "set_device_key_missing", flips.append)
    monkeypatch.setattr(key_store, "check_presence_async", lambda *a: flips.append("checked"))
    data = {"status_code": 409, "code": "byok_key_required", "message": "m"}
    assert "AI Provider Settings" in byok_notice.byok_error_message({"message": "m"}, data, 409)
    assert refreshes == [True] and flips == []


def test_receipt_shape_with_top_level_code_is_recognised_too(monkeypatch):
    from mixar.modules.byok.core import key_store

    _loaded(monkeypatch)
    monkeypatch.setattr(key_store, "check_presence_async", lambda *a: None)
    result = {"ok": False, "status_code": 409, "code": "byok_key_required", "message": "m"}
    assert "AI Provider Settings" in byok_notice.byok_error_message(result, {}, 409)


def test_client_codex_refusals_keep_their_message():
    expired = {"code": "byok_codex_expired"}
    text = byok_notice.byok_error_message({"message": "Codex sign-in expired"}, expired, None)
    assert text.startswith("Codex sign-in expired") and "AI Provider Settings" in text
    retry = {"code": "byok_codex_refresh_failed"}
    text = byok_notice.byok_error_message({"message": "NET-7"}, retry, None)
    assert text.startswith("NET-7") and "try again" in text


def test_a_409_without_the_byok_code_is_not_byok(monkeypatch):
    """The server always sends the code with its 409; a bare 409 (a future
    conflict on chat/input) must not touch the card for a platform user."""
    touched = []
    monkeypatch.setattr(credential_state, "set_device_key_missing", touched.append)
    monkeypatch.setattr(credential_state, "refresh", lambda: touched.append("refresh"))
    assert byok_notice.byok_error_message({"message": "busy"}, {"status_code": 409}, 409) is None
    assert touched == []


def test_other_errors_are_not_byok():
    assert byok_notice.byok_error_message({"message": "boom"}, {"status_code": 500}, 500) is None
    assert byok_notice.byok_error_message({"message": "credits"}, {"status_code": 402}, 402) is None
    assert byok_notice.byok_error_code({"code": -32020}, {"code": "other"}) == ""


def test_queue_processor_routes_byok_errors_before_the_credit_branch_and_never_retries():
    src = (SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core" / "queue_processor.py").read_text(encoding="utf-8")
    body = src[src.index("def handle_command_error("):src.index("def _handle_agent_error_internal(")]
    assert body.index("byok_error_message(") < body.index("is_credits_exhausted_error(status, message)")
    # Shown as an error bubble; nothing re-sends the command.
    assert "self._handle_agent_error_internal(byok_message, scene)" in body
    for resend in ("start_stream(", "start_input_stream(", "send_user_message("):
        assert resend not in body
