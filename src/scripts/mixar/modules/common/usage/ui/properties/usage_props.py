# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror of the cached usage snapshot.

The profile card is drawn in C++ (`interface_mixar_profile_card.cc`),
which cannot reach a Python module-level cache — so the snapshot that
``core/state.py`` owns is mirrored onto RNA here, and the card reads
these properties.

**WindowManager, never Scene**: this is session state that must not be
serialized into a ``.blend`` (a shared file would carry one user's plan
and credit balance to whoever opens it). ``mixie_chat_user_id`` uses
process-local RNA accessors; ``SKIP_SAVE`` alone does not protect Scene data.

``core/state.py`` stays the source of truth; these are a projection of
it, written on the main thread by ``core/poller._apply_snapshot``.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

#: Every property this module attaches, for a clean unregister.
_PROP_NAMES = (
    "mixar_usage_ready",
    "mixar_usage_has_subscription",
    "mixar_usage_plan_name",
    "mixar_usage_credits_remaining",
    "mixar_usage_monthly_remaining",
    "mixar_usage_bonus_remaining",
    "mixar_usage_has_allowance",
    "mixar_usage_can_top_up",
    "mixar_usage_stale",
    "mixar_account_name",
)


def register() -> None:
    wm = bpy.types.WindowManager

    wm.mixar_usage_ready = BoolProperty(
        name="Usage Ready",
        description="Whether a billing snapshot has been fetched at least once",
        default=False,
    )
    wm.mixar_usage_has_subscription = BoolProperty(
        name="Has Subscription",
        description="Whether the account has an active subscription to meter",
        default=False,
    )
    wm.mixar_usage_plan_name = StringProperty(
        name="Plan Name",
        description="Display name of the current plan",
        default="",
        maxlen=64,
    )
    wm.mixar_usage_credits_remaining = IntProperty(
        name="Credits Remaining",
        description="Total credits available (monthly allowance plus bonus credits)",
        default=0,
        min=0,
    )
    wm.mixar_usage_monthly_remaining = IntProperty(
        name="Monthly Credits Remaining",
        description="Credits left in the plan's monthly allowance",
        default=0,
        min=0,
    )
    wm.mixar_usage_bonus_remaining = IntProperty(
        name="Bonus Credits Remaining",
        description="Top-up, referral and sign-up bonus credits left",
        default=0,
        min=0,
    )
    wm.mixar_usage_has_allowance = BoolProperty(
        name="Has Allowance",
        description="Whether a monthly plan allowance backs part of the balance",
        default=False,
    )
    wm.mixar_usage_can_top_up = BoolProperty(
        name="Can Top Up",
        description="Whether this account is eligible to buy extra credits",
        default=False,
    )
    wm.mixar_usage_stale = BoolProperty(
        name="Usage Stale",
        description="Whether the last refresh failed and the figures shown are old",
        default=False,
    )
    wm.mixar_account_name = StringProperty(
        name="Account Name",
        description="Display name for the account greeting",
        default="",
        maxlen=128,
        options={'SKIP_SAVE'},
    )


def unregister() -> None:
    for name in _PROP_NAMES:
        try:
            delattr(bpy.types.WindowManager, name)
        except Exception:  # noqa: BLE001 — never registered / already gone
            pass
