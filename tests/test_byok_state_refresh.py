# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK credential state: who refreshes it, and what a failure may do.

History this pins, because it cost a user a whole session's worth of confusion:
BYOK moved onto the agent WebSocket, `agent_rpc.get_client()` raises when that
socket is absent or un-handshaken, and the post-login fetch fires on the same
tick that merely *initiates* the connection. Every cold start failed, the
failure handler cleared the mirror, and nothing re-fetched — so AI Provider
Settings showed "Not configured" over a credential that was stored and being
resolved on every turn (Langfuse stamped those turns `[BYOK]` throughout).

Settings are back on HTTP, so the invariants are:

1. Chat must not reference byok at all — the connect-edge workaround is gone.
2. Login is the trigger, via `refresh_agent_settings()`.
3. A FAILED fetch leaves the mirror alone.
4. A fetch that resolves AFTER a logout must not repopulate the previous
   account's provider and key preview. Over the socket this self-healed
   (logout dropped the connection); over HTTP the request completes with a
   still-valid token, so the epoch guard is load-bearing.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import credential_state
from mixar.modules.byok.ui.operators import byok_state_ops

CHAT_CORE = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core"
CONNECTION_MANAGER = CHAT_CORE / "connection_manager.py"
AUTH_OPS = (
    SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "ui" / "operators" / "auth_ops.py"
)
BYOK_OPS = SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators" / "byok_ops.py"

MIRROR_FIELDS = (
    "byok_is_active",
    "byok_current_provider",
    "byok_current_model",
    "byok_current_supports_vision",
    "byok_key_preview",
)

SERVER_PAYLOAD = {
    "byok_active": True,
    "items": [{
        "provider": "codex",
        "model": "gpt-6-astra",
        "supports_vision": True,
        "key_preview": "ChatGPT · someone@example.com",
    }],
}


def _wm():
    return SimpleNamespace(**{f: None for f in MIRROR_FIELDS})


def _fresh():
    """Reset the module singleton between tests."""
    credential_state.clear(_wm())


# ---------------------------------------------------------------------------
# 1 + 2: who triggers the refresh
# ---------------------------------------------------------------------------

def test_chat_no_longer_reaches_into_byok():
    """The connect-edge hook was a workaround for the socket transport.

    Keeping it would fire two extra requests on every reconnect (blips,
    sleep/wake, backend redeploys) and keep chat coupled to byok for no reason.
    """
    source = CONNECTION_MANAGER.read_text(encoding="utf-8")
    assert "byok" not in source.lower()
    assert "_refresh_byok_state" not in source


def test_login_paths_refresh_agent_settings_and_logout_invalidates():
    tree = ast.parse(AUTH_OPS.read_text(encoding="utf-8"))
    called = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    # Startup token validation, auto SSO re-login, interactive SSO login.
    assert called.count("refresh_agent_settings") == 3
    assert called.count("invalidate_agent_settings") == 1
    # The socket-race workaround is gone, not merely unused.
    assert "_schedule_byok_fetch" not in AUTH_OPS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3: a failed fetch is non-destructive
# ---------------------------------------------------------------------------

def test_failed_fetch_keeps_cached_state():
    _fresh()
    wm = _wm()
    credential_state.apply_from_payload(SERVER_PAYLOAD, wm)

    byok_state_ops._on_fetch_done(
        False, None, "Connection timed out. (NET-TIMEOUT)"
    )

    state = credential_state.snapshot()
    assert state["byok_is_active"] is True
    assert state["byok_current_provider"] == "codex"
    assert state["byok_key_preview"] == "ChatGPT · someone@example.com"


def test_server_reported_removal_still_clears():
    """Only the server retires a credential — through the SUCCESS path."""
    _fresh()
    credential_state.apply_from_payload(SERVER_PAYLOAD, _wm())

    byok_state_ops._on_fetch_done(True, {"byok_active": False, "items": []}, None)

    assert credential_state.snapshot()["byok_is_active"] is False


def test_successful_fetch_applies_server_state():
    _fresh()
    byok_state_ops._on_fetch_done(True, SERVER_PAYLOAD, None)

    state = credential_state.snapshot()
    assert state["byok_is_active"] is True
    assert state["byok_current_provider"] == "codex"
    assert state["byok_current_model"] == "gpt-6-astra"


def test_state_mirrors_onto_the_window_manager():
    _fresh()
    wm = _wm()
    credential_state.apply_from_payload(SERVER_PAYLOAD, wm)

    assert wm.byok_is_active is True
    assert wm.byok_current_provider == "codex"
    assert wm.byok_key_preview == "ChatGPT · someone@example.com"


# ---------------------------------------------------------------------------
# 4: the epoch guard
# ---------------------------------------------------------------------------

def test_a_fetch_that_lands_after_logout_is_dropped(monkeypatch):
    """The previous account's provider must never appear for the next one.

    Over HTTP the in-flight request completes with a still-valid bearer token,
    so nothing but the epoch stops the callback from writing it back.
    """
    _fresh()
    captured = {}
    monkeypatch.setattr(
        credential_state.byok_client, "fetch_state",
        lambda on_done: captured.update(on_done=on_done),
    )

    credential_state.refresh()          # user A's fetch starts
    credential_state.clear(_wm())       # user A logs out
    captured["on_done"](True, SERVER_PAYLOAD, None)  # ...and it lands late

    state = credential_state.snapshot()
    assert state["byok_is_active"] is False
    assert state["byok_current_provider"] == ""


def test_a_fetch_that_lands_normally_is_applied(monkeypatch):
    """The epoch guard must not swallow the ordinary case."""
    _fresh()
    captured = {}
    monkeypatch.setattr(
        credential_state.byok_client, "fetch_state",
        lambda on_done: captured.update(on_done=on_done),
    )

    credential_state.refresh()
    captured["on_done"](True, SERVER_PAYLOAD, None)

    assert credential_state.snapshot()["byok_current_provider"] == "codex"


# ---------------------------------------------------------------------------
# 4b: the save echo carries the submit-time epoch
# ---------------------------------------------------------------------------

def test_a_save_echo_that_lands_after_logout_is_dropped():
    """The PUT is async (up to 15 s). Save, then log out before it lands: the
    echo must not write the logged-out account's provider back into the mirror.
    """
    _fresh()
    stale = credential_state.current_epoch()   # captured at submit time
    wm = _wm()
    credential_state.clear(wm)                 # ...then the user logs out
    wm = _wm()                                 # a fresh, untouched mirror

    applied = credential_state.apply_from_payload(SERVER_PAYLOAD, wm, epoch=stale)

    assert applied is False
    state = credential_state.snapshot()
    assert state["byok_is_active"] is False
    assert state["byok_current_provider"] == ""
    assert all(getattr(wm, f) is None for f in MIRROR_FIELDS)


def test_a_save_echo_with_the_current_epoch_is_applied():
    """The epoch guard must not swallow the ordinary save."""
    _fresh()
    wm = _wm()

    applied = credential_state.apply_from_payload(
        SERVER_PAYLOAD, wm, epoch=credential_state.current_epoch()
    )

    assert applied is True
    assert credential_state.snapshot()["byok_current_provider"] == "codex"
    assert wm.byok_current_provider == "codex"


def test_every_save_submit_binds_the_epoch_capturing_callback():
    """`bpy` is a mock here, so the operators are pinned at source level: no
    submit path may hand the client a bare `_on_save_done` — it must go
    through `_save_callback()`, which captures `current_epoch()` at submit.
    """
    source = BYOK_OPS.read_text(encoding="utf-8")
    assert "on_done=_on_save_done" not in source
    tree = ast.parse(source)
    on_done_values = [
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "on_done"
    ]
    save_submits = [
        v for v in on_done_values
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
        and v.func.id == "_save_callback"
    ]
    # execute (cloud), _execute_openrouter, _execute_codex, _execute_local.
    assert len(save_submits) == 4
    assert "credential_state.current_epoch()" in source
