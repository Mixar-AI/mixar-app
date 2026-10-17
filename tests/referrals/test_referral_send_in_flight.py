# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refer a Friend: reopening the dialog never re-arms a send in flight.

``reset`` + ``load`` on reopen used to flip the state back to READY (Send
enabled) and bump the shared generation, so the send's reply was dropped:
drafts stayed, no notice showed, and a second press emailed the friends again.
"""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from mixar.modules.referrals import constants as C
from mixar.modules.referrals.core import flow

SENT = SimpleNamespace(data={"status": "success", "data": {"results": [
    {"email": "a@example.com", "status": "sent"},
]}})


def _wm():
    return SimpleNamespace(
        windows=[],
        mixar_referral_state=C.STATE_READY,
        mixar_referral_url="https://mixar.app/auth/signup?ref=MXR-1",
        mixar_referral_emails="a@example.com", mixar_referral_error="",
        mixar_referral_notice="", mixar_referral_notice_kind=C.NOTICE_INFO,
        mixar_referral_details="", mixar_referral_invitee_award=0,
        mixar_referral_inviter_award=0, mixar_referral_paid_total=0,
        mixar_referral_count=0,
    )


@pytest.fixture
def harness(monkeypatch):
    sends, loads = [], []

    class _Service:
        def dashboard_async(self, *, on_success, on_error):
            loads.append((on_success, on_error))

        def invite_emails_async(self, emails, *, on_success, on_error):
            sends.append((on_success, on_error))

    fake = ModuleType("mixar.modules.common.api.services")
    fake.get_referral_service = lambda: _Service()
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(flow, "_send_in_flight", False)
    state = SimpleNamespace(wm=_wm(), sends=sends, loads=loads)
    monkeypatch.setattr(flow, "_wm", lambda: state.wm)
    return state


def _send_poll(wm):
    # MIXAR_OT_referral_send_invites.poll
    return wm.mixar_referral_state == C.STATE_READY


def test_reopen_mid_send_keeps_sending_and_the_reply_still_lands(harness):
    wm = harness.wm
    flow.send(wm, ["a@example.com"])
    assert wm.mixar_referral_state == C.STATE_SENDING

    flow.reset(wm)  # the dialog is reopened while the send is in flight
    flow.load()
    assert wm.mixar_referral_state == C.STATE_SENDING
    assert not _send_poll(wm)

    # The revalidation lands first: it must not re-arm Send either.
    harness.loads[-1][0](SimpleNamespace(data={"status": "success", "data": {
        "invite_url": wm.mixar_referral_url, "award_amounts": {}}}))
    assert not _send_poll(wm)

    harness.sends[-1][0](SENT)
    assert wm.mixar_referral_emails == ""
    assert wm.mixar_referral_notice == "Invite sent to 1 friend"
    assert wm.mixar_referral_state == C.STATE_READY
    assert flow._send_in_flight is False

    flow.reset(wm)  # a later reopen is back to normal
    assert wm.mixar_referral_state == C.STATE_READY
    assert wm.mixar_referral_notice == ""


def test_logout_mid_send_drops_the_reply(harness):
    wm = harness.wm
    flow.send(wm, ["a@example.com"])
    flow.clear(wm)
    assert flow._send_in_flight is False
    wm.mixar_referral_emails = "next-account@example.com"

    harness.sends[-1][0](SENT)
    assert wm.mixar_referral_emails == "next-account@example.com"
    assert wm.mixar_referral_notice == ""
    assert wm.mixar_referral_state == C.STATE_LOADING

    harness.sends[-1][1](RuntimeError("late"))
    assert wm.mixar_referral_notice == ""


def test_a_failed_send_rearms_send_with_its_notice(harness):
    wm = harness.wm
    flow.send(wm, ["a@example.com"])
    flow.reset(wm)
    harness.sends[-1][1](RuntimeError("Daily invite limit reached"))
    assert wm.mixar_referral_state == C.STATE_READY
    assert wm.mixar_referral_notice_kind == C.NOTICE_ERROR
    assert wm.mixar_referral_emails == "a@example.com"
