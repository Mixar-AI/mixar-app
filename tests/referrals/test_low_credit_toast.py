# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Low-credit toast: when it fires, what it offers, and its wiring."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.referrals import constants as C
from mixar.modules.referrals.core import low_credit

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/scripts/mixar/modules"
T = C.LOW_CREDIT_THRESHOLD


def reading(credits, *, error="", subscribed=True, fetched_at=1.0):
    return SimpleNamespace(credits_remaining=credits, error=error,
                           has_subscription=subscribed, fetched_at=fetched_at)


EMPTY = reading(0, subscribed=False, fetched_at=0.0)


@pytest.mark.parametrize("before, after, fires", [
    (T + 1, T, True),        # lands exactly on the threshold
    (900, 40, True),         # one generation jumps well past it
    (T + 50, 0, True),       # straight to empty still counts
    (T, T - 10, False),      # already low: not a crossing
    (150, 120, False),
    (400, T + 1, False),     # still above
])
def test_fires_only_on_a_crossing(before, after, fires):
    assert low_credit.crossed(reading(before), reading(after)) is fires


def test_first_reading_errors_and_unmetered_accounts_never_fire():
    assert not low_credit.crossed(EMPTY, reading(10))              # opened the app low / just logged in
    assert not low_credit.crossed(reading(900), reading(10, error="timeout"))
    assert not low_credit.crossed(reading(900), reading(0, subscribed=False))


def test_a_failed_fetch_in_between_neither_fires_nor_hides_the_crossing():
    # snapshot_error keeps the previous figures, error set.
    assert not low_credit.crossed(reading(600), reading(600, error="timeout"))
    assert low_credit.crossed(reading(600, error="timeout"), reading(150))


class _Store:
    def __init__(self):
        self.pushed, self.dismissed = [], []

    def push(self, **kw):
        self.pushed.append(kw)
        return kw["id"]

    def dismiss(self, nid):
        self.dismissed.append(nid)


@pytest.fixture
def store(monkeypatch):
    from mixar.modules.common.notifications import store as store_mod

    fake = _Store()
    monkeypatch.setattr(store_mod, "get_notification_store", lambda: fake)
    return fake


def test_crossing_pushes_one_sticky_toast_whose_button_opens_refer_a_friend(store):
    assert low_credit.notify_if_crossed(reading(900), reading(180))
    assert not low_credit.notify_if_crossed(reading(180), reading(90))
    (toast,) = store.pushed
    assert toast["id"] == C.LOW_CREDIT_NOTIFICATION_ID
    assert toast["title"] == "Running low on credits"
    assert "180 credits left" in toast["body"]
    assert toast["dismissible"] is True
    (action,) = toast["actions"]
    assert (action.label, action.operator, action.style) == (
        "Refer a Friend", "mixar.refer_friend_via_profile", "primary")


def test_opening_refer_a_friend_dismisses_the_toast(store):
    low_credit.dismiss_toast()
    assert store.dismissed == [C.LOW_CREDIT_NOTIFICATION_ID]
    ops = (MODULE / "referrals/ui/operators/referral_ops.py").read_text(encoding="utf-8")
    cls = ops[ops.index("class MIXAR_OT_refer_friend(Operator)"):]
    invoke = cls[cls.index("def invoke"):cls.index("def execute")]
    assert "low_credit.dismiss_toast()" in invoke


def test_poller_checks_every_applied_reading():
    poller = (MODULE / "common/usage/core/poller.py").read_text(encoding="utf-8")
    apply_fn = poller[poller.index("def _apply_snapshot"):poller.index("def _schedule_apply")]
    assert "_notify_low_credit(previous, snapshot)" in apply_fn


def test_card_row_is_the_open_cards_refer_a_friend_button():
    widgets = [
        {"op": "MIXAR_OT_refer_friend", "w": 7, "rect": [0, 0, 10, 10]},     # not a popup
        {"op": "MIXAR_OT_refer_friend", "w": 8, "popup": True, "rect": [0, 0, 10, 10]},
        {"op": "MIXIE_CHAT_OT_open_dashboard", "w": 7, "popup": True, "rect": [0, 0, 9, 9]},
        {"op": "MIXAR_OT_refer_friend", "w": 7, "popup": True, "rect": [100, 40, 300, 80]},
    ]
    assert low_credit.refer_row_center(widgets, 7) == (200, 60)
    assert low_credit.refer_row_center(widgets[:3], 7) is None


def test_toast_button_opens_the_card_under_its_chip_then_the_dialog():
    ops = (MODULE / "referrals/ui/operators/referral_ops.py").read_text(encoding="utf-8")
    assert 'bl_idname = "mixar.refer_friend_via_profile"' in ops
    assert "low_credit.open_via_profile()" in ops
    core = (MODULE / "referrals/core/low_credit.py").read_text(encoding="utf-8")
    assert "opener(panel=PROFILE_PANEL)" in core and 'PROFILE_PANEL = "MIXAR_PT_profile"' in core
    assert "target.cursor_warp(*row)" in core
    src = ROOT / "src/source/blender"
    opener = (src / "editors/interface/mixar/tour_menu.cc").read_text(encoding="utf-8")
    # The card is opened through the chip's own (activated) button, never
    # attached to an inactive one, whose pointer dangles once the top bar
    # rebuilds its blocks.
    assert "ui::button_activate_event(C, region, but);" in opener
    assert "popover_panel_create" not in opener
    handlers = (src / "editors/interface/interface_handlers.cc").read_text(encoding="utf-8")
    block = handlers[handlers.index("static int do_but_BLOCK"):][:3000]
    assert "EVT_RETKEY, EVT_BUT_OPEN) &&" in block
    rna = (src / "makesrna/intern/rna_wm_mixar.cc").read_text(encoding="utf-8")
    assert '"mixar_tour_popover_open"' in rna
