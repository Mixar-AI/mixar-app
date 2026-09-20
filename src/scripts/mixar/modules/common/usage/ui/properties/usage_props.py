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
and credit balance to whoever opens it). ``mixie_chat_user_id`` sets the
same precedent with ``SKIP_SAVE``.

``core/state.py`` stays the source of truth; these are a projection of
it, written on the main thread by ``core/poller._apply_snapshot``.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

#: Every property this module attaches, for a clean unregister.
_PROP_NAMES = (
    "mixar_usage_ready",
    "mixar_usage_has_subscription",
    "mixar_usage_plan_name",
    "mixar_usage_remaining_pct",
    "mixar_usage_credits_remaining",
    "mixar_usage_credits_total",
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
    wm.mixar_usage_remaining_pct = FloatProperty(
        name="Remaining",
        description="Percentage of the cycle credit allocation still available",
        default=0.0,
        min=0.0,
        max=100.0,
    )
    wm.mixar_usage_credits_remaining = IntProperty(
        name="Credits Remaining",
        description="Credits left in the current cycle",
        default=0,
        min=0,
    )
    wm.mixar_usage_credits_total = IntProperty(
        name="Credits Total",
        description="Credit allocation for the current cycle",
        default=0,
        min=0,
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
