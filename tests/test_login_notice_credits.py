# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

""""Sign in & use Mixar credits" on the sign-in notice means it.

QA 2026-10-20 (uat8, reproduced in the harness): a guest refused at the
credit gate pressed the notice's Sign in to switch to Mixar's models. The
account they signed in to had its own Codex key active (saved on another
computer), so the notice's resend went out keyless and came back as the
"Link your ChatGPT sign-in" card. Pinned here
(space_mixie_chat/core/login_notice.py, byok/ui/operators/byok_toggle_ops.py):

- a notice whose alternative is a key (``login_or_byok`` / ``fix_byok``)
  remembers that its Sign in asked for credits;
- once the account's credential state is known, an ACTIVE key is paused
  (the island's Mixie pause: rows deleted, this computer's record kept),
  then the message is resent, and the notice stays saying so;
- no active key: a plain resend, the notice goes;
- a pause that cannot start or fails still resends (the server decides);
- a plain ``login`` notice, a guest session or a saved key never pause.
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

from mixar.modules.byok.core import credential_state  # noqa: E402
from mixar.modules.byok.ui.operators import byok_toggle_ops  # noqa: E402

PAUSED = "**You're signed in**\n\nSwitched to Mixar credits — your Codex key is paused."


class _Items(list):
    def add(self):
        item = SimpleNamespace(label="", value="", style="")
        self.append(item)
        return item


class _Messages(list):
    def add(self):
        msg = SimpleNamespace(bubble_id="", sender="", message_type="", content="", text="",
                              action_items=_Items())
        self.append(msg)
        return msg

    def remove(self, index):
        del self[index]


@pytest.fixture
def rig(monkeypatch):
    """A notice in one scene, a pending refused message, a live socket; the
    credential mirror, the pause and the resend are recorded."""
    pytest.importorskip("cryptography")  # space_mixie_chat.core imports the executor
    from mixar.modules.space_mixie_chat.core import byok_resend, login_notice

    scene = SimpleNamespace(mixie_chat_messages=_Messages(), mixie_session_id="s-1",
                            mixie_chat_layout_epoch=0)
    wm = SimpleNamespace(mixie_chat_is_logged_in=False, mixie_chat_is_guest=True)
    calls = SimpleNamespace(resent=[], timers=[], logins=[], pauses=[], hooks=[],
                            state={"byok_state_loaded": False, "byok_is_active": False,
                                   "byok_current_provider": ""}, pause_starts=True)
    monkeypatch.setattr(login_notice, "redraw_chat_areas", lambda: None)
    monkeypatch.setattr(login_notice, "_notices", {})
    monkeypatch.setattr(login_notice, "_connected", lambda: True)
    monkeypatch.setattr(login_notice.bpy, "data", SimpleNamespace(scenes=[scene]), raising=False)
    monkeypatch.setattr(login_notice.bpy, "context", SimpleNamespace(window_manager=wm), raising=False)
    monkeypatch.setattr(login_notice.bpy, "ops", SimpleNamespace(mixie_chat=SimpleNamespace(
        login=lambda: calls.logins.append(1) or {'FINISHED'})), raising=False)
    monkeypatch.setattr(login_notice.bpy.app, "timers", SimpleNamespace(
        register=lambda fn, first_interval=0.0: calls.timers.append(fn)), raising=False)
    monkeypatch.setattr(byok_resend, "pending", lambda sid: object() if sid == "s-1" else None)
    monkeypatch.setattr(byok_resend, "resend", lambda sid: calls.resent.append(sid) or True)
    monkeypatch.setattr(byok_resend, "_scene_for", lambda sid: scene)
    monkeypatch.setattr(credential_state, "snapshot", lambda: dict(calls.state))
    monkeypatch.setattr(credential_state, "pending", lambda: "")
    monkeypatch.setattr(credential_state, "on_next_fetch", calls.hooks.append)

    def pause(wm_arg, then=None, otherwise=None):
        calls.pauses.append(SimpleNamespace(wm=wm_arg, then=then, otherwise=otherwise))
        return calls.pause_starts

    monkeypatch.setattr(byok_toggle_ops, "pause", pause)
    return SimpleNamespace(notice=login_notice, scene=scene, wm=wm, calls=calls)


def _post(rig, cta="login_or_byok"):
    rig.notice.add_login_required_chat_message(rig.scene, cta=cta, body="Sign in or add a key")
    return rig.scene.mixie_chat_messages[0]


def _sign_in(rig, *, codex_active):
    """Press the notice's Sign in, let the browser sign-in land, then the
    account's credential fetch."""
    rig.notice.sign_in_clicked(rig.scene)
    assert rig.calls.logins == [1]
    rig.wm.mixie_chat_is_logged_in, rig.wm.mixie_chat_is_guest = True, False
    rig.notice.session_ready(is_guest=False)
    rig.calls.state = {"byok_state_loaded": True, "byok_is_active": codex_active,
                       "byok_current_provider": "codex" if codex_active else ""}
    for hook in rig.calls.hooks:
        hook(True)


def _run_resend(rig):
    assert rig.calls.timers, "nothing was scheduled"
    return rig.calls.timers[-1]()


def test_an_active_account_key_is_paused_before_the_resend(rig):
    msg = _post(rig)
    rig.notice.sign_in_clicked(rig.scene)
    rig.wm.mixie_chat_is_logged_in, rig.wm.mixie_chat_is_guest = True, False
    rig.notice.session_ready(is_guest=False)
    # The sign-in cleared the mirror: nothing is decided before its fetch lands.
    assert msg.content == "**You're signed in**\n\nSwitching to Mixar credits…"
    assert rig.calls.pauses == [] and rig.calls.resent == [] and len(rig.calls.hooks) == 1
    rig.calls.state = {"byok_state_loaded": True, "byok_is_active": True,
                       "byok_current_provider": "codex"}
    rig.calls.hooks[0](True)
    assert len(rig.calls.pauses) == 1 and rig.calls.pauses[0].wm is rig.wm
    assert rig.calls.resent == []  # the resend waits on the pause's echo
    rig.calls.pauses[0].then()
    assert _run_resend(rig) is None and rig.calls.resent == ["s-1"]
    # The notice stays and says what changed.
    assert len(rig.scene.mixie_chat_messages) == 1 and msg.content == PAUSED
    assert len(msg.action_items) == 0


def test_an_account_without_a_key_just_resends(rig):
    _post(rig)
    _sign_in(rig, codex_active=False)
    assert rig.calls.pauses == []
    assert _run_resend(rig) is None and rig.calls.resent == ["s-1"]
    assert len(rig.scene.mixie_chat_messages) == 0  # the old behaviour: the notice goes


def test_fix_byok_sign_in_pauses_too(rig):
    msg = _post(rig, cta="fix_byok")
    assert [a.label for a in msg.action_items] == ["Fix key", "Sign in & use Mixar credits"]
    _sign_in(rig, codex_active=True)
    assert len(rig.calls.pauses) == 1


def test_a_plain_sign_in_notice_never_pauses(rig):
    _post(rig, cta="login")
    _sign_in(rig, codex_active=True)
    assert rig.calls.pauses == [] and rig.calls.hooks == []
    assert _run_resend(rig) is None and rig.calls.resent == ["s-1"]


def test_a_pause_that_cannot_start_still_resends(rig):
    rig.calls.pause_starts = False
    _post(rig)
    _sign_in(rig, codex_active=True)
    assert len(rig.calls.pauses) == 1
    assert _run_resend(rig) is None and rig.calls.resent == ["s-1"]
    assert len(rig.scene.mixie_chat_messages) == 0


def test_a_failed_pause_still_resends_without_the_paused_line(rig):
    _post(rig)
    _sign_in(rig, codex_active=True)
    rig.calls.pauses[0].otherwise()
    assert _run_resend(rig) is None and rig.calls.resent == ["s-1"]
    assert len(rig.scene.mixie_chat_messages) == 0


def test_already_signed_in_decides_at_once(rig):
    msg = _post(rig)
    rig.wm.mixie_chat_is_logged_in, rig.wm.mixie_chat_is_guest = True, False
    rig.calls.state = {"byok_state_loaded": True, "byok_is_active": True,
                       "byok_current_provider": "codex"}
    rig.notice.sign_in_clicked(rig.scene)
    assert rig.calls.logins == [] and rig.calls.hooks == [] and len(rig.calls.pauses) == 1
    rig.calls.pauses[0].then()
    _run_resend(rig)
    assert msg.content == PAUSED


def test_nothing_to_resend_still_pauses_and_asks_for_the_send(rig, monkeypatch):
    from mixar.modules.space_mixie_chat.core import byok_resend
    monkeypatch.setattr(byok_resend, "pending", lambda sid: None)
    msg = _post(rig)
    _sign_in(rig, codex_active=True)
    rig.calls.pauses[0].then()
    assert msg.content == ("**You're signed in**\n\nSwitched to Mixar credits — your Codex key "
                           "is paused.\n\nSend your message again to continue.")


def test_a_guest_session_or_a_saved_key_never_pauses(rig):
    _post(rig, cta="login_or_byok")
    rig.notice.sign_in_clicked(rig.scene)
    rig.notice.key_saved()  # the dialog saved a key meanwhile: that answers it
    assert rig.calls.pauses == [] and rig.calls.hooks == []


def test_the_pause_reports_failure_to_its_caller(monkeypatch):
    """`byok_toggle_ops.pause(otherwise=…)`: the chat notice resends after a
    failed pause too; `then` stays success-only (the island's hosted pick)."""
    ran = []
    monkeypatch.setattr(credential_state, "current_epoch", lambda: 1)
    monkeypatch.setattr(credential_state, "end_pending", lambda: None)
    monkeypatch.setattr(credential_state, "refresh", lambda: None)
    monkeypatch.setattr(credential_state, "apply_removed", lambda epoch=None: True)
    monkeypatch.setattr(byok_toggle_ops.preference_state, "refresh", lambda: None)
    monkeypatch.setattr(byok_toggle_ops.preference_state, "invalidate_reads", lambda: None)
    monkeypatch.setattr(byok_toggle_ops.preference_state, "apply_local", lambda *a, **k: None)
    monkeypatch.setattr(byok_toggle_ops, "_toast", lambda *a: None)
    monkeypatch.setattr(byok_toggle_ops, "_redraw", lambda: None)
    byok_toggle_ops._on_pause_done(False, 0, "down", 1, 1, then=lambda: ran.append("then"),
                                   otherwise=lambda: ran.append("otherwise"))
    byok_toggle_ops._on_pause_done(True, 2, None, 1, 1, then=lambda: ran.append("then"),
                                   otherwise=lambda: ran.append("otherwise"))
    assert ran == ["otherwise", "then"]
