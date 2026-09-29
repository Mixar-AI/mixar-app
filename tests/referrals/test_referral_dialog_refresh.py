# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refer a Friend: the open dialog is rebuilt when the async load lands, and
the link is cached for the session.

Regression for "Getting your invite link…" sticking on screen: a props
dialog re-runs ``draw()`` only when its pop-up region is tagged for a UI
refresh. ``area.tag_redraw()`` and WM property writes never reach it, so the
load's answer stayed invisible until an unrelated window event.
"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from mixar.modules.referrals import constants as C
from mixar.modules.referrals.core import flow

ROOT = Path(__file__).resolve().parents[2]
RNA_CC = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"
TOUR_CC = ROOT / "src/source/blender/editors/interface/mixar/tour_menu.cc"
AUTH_OPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/auth_ops.py"

DASHBOARD = {"status": "success", "data": {
    "invite_url": "https://mixar.app/auth/signup?ref=MXR-1",
    "award_amounts": {"invitee": 500, "inviter": 500, "paid_total": 2000},
    "qualified_count": 2,
}}


class _Window:
    def __init__(self):
        self.refreshes = 0
        self.screen = SimpleNamespace(areas=[])

    def mixar_refresh_popups(self):
        self.refreshes += 1
        return 1


def _wm(**overrides):
    wm = SimpleNamespace(
        windows=[_Window()],
        mixar_referral_state=C.STATE_LOADING, mixar_referral_url="",
        mixar_referral_emails="", mixar_referral_error="",
        mixar_referral_notice="", mixar_referral_notice_kind=C.NOTICE_INFO,
        mixar_referral_details="", mixar_referral_invitee_award=0,
        mixar_referral_inviter_award=0, mixar_referral_paid_total=0,
        mixar_referral_count=0,
    )
    for key, value in overrides.items():
        setattr(wm, key, value)
    return wm


@pytest.fixture
def harness(monkeypatch):
    calls = []

    class _Service:
        def dashboard_async(self, *, on_success, on_error):
            calls.append((on_success, on_error))

    # A stand-in module: the real services package pulls in keyring via auth.
    fake = ModuleType("mixar.modules.common.api.services")
    fake.get_referral_service = lambda: _Service()
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    state = SimpleNamespace(wm=_wm(), calls=calls)
    monkeypatch.setattr(flow, "_wm", lambda: state.wm)
    return state


def _refreshes(wm):
    return sum(w.refreshes for w in wm.windows)


def test_loaded_link_rebuilds_the_open_dialog(harness):
    wm = harness.wm
    flow.reset(wm)
    assert wm.mixar_referral_state == C.STATE_LOADING
    flow.load()
    on_success, _ = harness.calls[-1]
    on_success(SimpleNamespace(data=DASHBOARD))
    assert wm.mixar_referral_state == C.STATE_READY
    assert wm.mixar_referral_url.endswith("MXR-1")
    assert _refreshes(wm) == 1, "the dialog's pop-up region must be tagged"


def test_failed_load_rebuilds_the_open_dialog(harness):
    flow.reset(harness.wm)
    flow.load()
    _, on_error = harness.calls[-1]
    on_error(RuntimeError("boom"))
    assert harness.wm.mixar_referral_state == C.STATE_ERROR
    assert _refreshes(harness.wm) == 1


def test_cached_link_opens_ready_and_revalidates_quietly(harness):
    wm = harness.wm
    flow.reset(wm)
    flow.load()
    harness.calls[-1][0](SimpleNamespace(data=DASHBOARD))
    before = _refreshes(wm)

    flow.reset(wm)  # reopen
    assert wm.mixar_referral_state == C.STATE_READY, "no loading screen on reopen"
    flow.load()
    harness.calls[-1][0](SimpleNamespace(data=DASHBOARD))
    assert _refreshes(wm) == before, "an unchanged answer must not rebuild the dialog"

    flow.load()
    harness.calls[-1][1](RuntimeError("offline"))
    assert wm.mixar_referral_state == C.STATE_READY, "keep the cached link on a failed revalidation"


def test_revalidation_does_not_end_a_send(harness):
    wm = harness.wm
    flow.reset(wm)
    flow.load()
    harness.calls[-1][0](SimpleNamespace(data=DASHBOARD))
    wm.mixar_referral_state = C.STATE_SENDING
    flow.load()
    harness.calls[-1][0](SimpleNamespace(data=DASHBOARD))
    assert wm.mixar_referral_state == C.STATE_SENDING


def test_logout_clears_the_cache_and_drops_in_flight_answers(harness):
    wm = harness.wm
    flow.reset(wm)
    flow.load()
    harness.calls[-1][0](SimpleNamespace(data=DASHBOARD))
    wm.mixar_referral_emails = "friend@x.com"
    flow.load()
    in_flight = harness.calls[-1][0]
    flow.clear(wm)
    in_flight(SimpleNamespace(data=DASHBOARD))
    assert wm.mixar_referral_url == "" and wm.mixar_referral_emails == ""
    flow.reset(wm)
    assert wm.mixar_referral_state == C.STATE_LOADING


def test_redraw_survives_a_build_without_the_native_refresh(harness):
    harness.wm.windows = [SimpleNamespace(screen=SimpleNamespace(areas=[]))]
    flow._redraw()  # no AttributeError


def test_native_refresh_tags_temporary_regions():
    rna = RNA_CC.read_text(encoding="utf-8")
    assert '"mixar_refresh_popups"' in rna
    tour = TOUR_CC.read_text(encoding="utf-8")
    body = tour[tour.index("int Mixar_refresh_popups"):]
    body = body[:body.index("\n}\n")]
    assert "screen->regionbase" in body and "RGN_TYPE_TEMPORARY" in body
    assert "ED_region_tag_refresh_ui" in body
    # Operator dialogs only: menus and popovers are never force-refreshed.
    assert "popup_op" in body


def test_logout_and_login_clear_referral_state():
    source = AUTH_OPS.read_text(encoding="utf-8")
    assert "referral_flow.clear(wm)" in source
    logout = source[source.index("class MIXIE_CHAT_OT_logout"):]
    assert "_clear_referral_state(wm)" in logout
    # An SSO login can switch accounts without a logout first.
    for marker in ('_capture_session_started("sso_relogin")',
                   '_capture_session_started("interactive_login")'):
        after = source[source.index(marker):].splitlines()[1]
        assert "_clear_referral_state(" in after
