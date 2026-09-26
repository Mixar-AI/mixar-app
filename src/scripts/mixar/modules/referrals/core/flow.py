# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Requests behind the Refer a Friend dialog, mirrored onto WindowManager.

Callbacks arrive on Blender's main thread (the shared request queue delivers
them there), so they write RNA directly. Every request carries a generation
number: reopening the dialog while an older load is in flight must not let
the stale answer overwrite the fresh state.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

from .. import constants as C
from . import invites

logger = get_logger(__name__)

_generation = 0


def _wm():
    try:
        return bpy.context.window_manager
    except Exception:  # noqa: BLE001 — during shutdown / file load
        return None


def _redraw() -> None:
    wm = _wm()
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def set_notice(wm, text: str, kind: str = C.NOTICE_INFO, details=()) -> None:
    wm.mixar_referral_notice = text
    wm.mixar_referral_notice_kind = kind
    wm.mixar_referral_details = "\n".join(details)


def reset(wm) -> None:
    """Fresh dialog state. The typed email draft survives a reopen."""
    wm.mixar_referral_state = C.STATE_LOADING
    wm.mixar_referral_error = ""
    set_notice(wm, "")


def load() -> None:
    """Fetch the invite link and award amounts for the signed-in user."""
    global _generation
    _generation += 1
    token = _generation

    from mixar.modules.common.api.services import get_referral_service

    def _on_success(response) -> None:
        wm = _wm()
        if wm is None or token != _generation:
            return
        data = invites.unwrap(response)
        url = data.get("invite_url") or ""
        if not url:
            wm.mixar_referral_state = C.STATE_ERROR
            wm.mixar_referral_error = "Referrals are not available right now"
            _redraw()
            return
        awards = data.get("award_amounts") or {}
        wm.mixar_referral_url = url
        wm.mixar_referral_invitee_award = int(awards.get("invitee") or 0)
        wm.mixar_referral_inviter_award = int(awards.get("inviter") or 0)
        wm.mixar_referral_paid_total = int(awards.get("paid_total") or 0)
        wm.mixar_referral_count = int(data.get("qualified_count") or 0)
        wm.mixar_referral_state = C.STATE_READY
        _redraw()

    def _on_error(error) -> None:
        wm = _wm()
        if wm is None or token != _generation:
            return
        logger.error("[Referrals] dashboard load failed: %s", error)
        wm.mixar_referral_state = C.STATE_ERROR
        wm.mixar_referral_error = invites.error_message(
            error, "Couldn't load your invite link")
        _redraw()

    get_referral_service().dashboard_async(on_success=_on_success, on_error=_on_error)


def send(wm, emails) -> None:
    """Ask the backend to email the invite link to *emails*."""
    from mixar.modules.common.api.services import get_referral_service

    token = _generation
    wm.mixar_referral_state = C.STATE_SENDING
    set_notice(wm, "")

    def _finish() -> None:
        live = _wm()
        if live is not None and token == _generation:
            live.mixar_referral_state = C.STATE_READY
        _redraw()

    def _on_success(response) -> None:
        live = _wm()
        if live is None or token != _generation:
            return
        headline, lines, all_sent = invites.summarize(invites.unwrap(response))
        if all_sent:
            live.mixar_referral_emails = ""
        set_notice(live, headline, C.NOTICE_INFO if all_sent else C.NOTICE_ERROR, lines)
        _finish()

    def _on_error(error) -> None:
        live = _wm()
        if live is None or token != _generation:
            return
        logger.error("[Referrals] invite emails failed: %s", error)
        set_notice(live, invites.error_message(error, "Couldn't send invites"),
                   C.NOTICE_ERROR)
        _finish()

    get_referral_service().invite_emails_async(
        emails, on_success=_on_success, on_error=_on_error)
