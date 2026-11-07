# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-recovery telemetry (``session_recovery``).

The funnel from "Mixar died" to "the work is back": an unclean exit found at
startup, a restore available and offered, the user's choice, the file read
and the follow-up (generations re-attached, the document retitled). Plus a
rate-limited signal when a save point could not be written.

Then the agent's side, for a tab whose agent was working at the crash: the
Continue notice shown (``continue_offered``, ``reshown`` after a refusal),
Continue sent (``continued``) or not sendable yet (``continue_blocked``),
refused by the backend (``continue_refused``), Start fresh
(``continue_dismissed``), and how the continued turn ended
(``continue_finished``: ``outcome`` and ``duration_s``).

Opaque ids and enums only: the recovery journal's session id and the crashed
process's ``app_session_id``; never a path, a file, document or scene name, a
prompt or a credential. Every property passes an allowlist here. Fail-open:
nothing in this module may raise into the recovery flow.
"""

from __future__ import annotations

import time

from .capture import capture
from .constants import EVENT_SESSION_RECOVERY_PREFIX

STAGES = frozenset({
    "unclean_exit_detected", "available", "offered", "requested", "scene_restored",
    "completed", "partial", "failed", "dismissed", "save_point_failed",
    "continue_offered", "continued", "continue_blocked", "continue_refused",
    "continue_dismissed", "continue_finished",
})
# The journal's candidate kinds, as analysis reads them.
CANDIDATE_KINDS = {
    "save_point": "save_point", "inherited": "save_point", "autosave": "autosave",
    "project": "project", "snapshot": "turn_checkpoint",
}
SURFACES = frozenset({"splash", "dialog", "file_menu", "chat"})
# How a continued agent turn ended (the turn_end status).
OUTCOMES = frozenset({"completed", "in_progress", "cancelled", "unavailable", "failed"})
FAILURE_CATEGORIES = frozenset({
    "read_cancelled", "read_error", "unavailable",            # a restore
    "jobs_not_reattached", "adoption_failed", "retitle_failed",  # a partial one
    "write_failed", "not_filed",                              # a save point
})
SAVE_POINT_FAILED_INTERVAL_S = 600.0

_last_save_point_failed = 0.0


def offer_properties(offer: dict | None) -> dict:
    """The allowlisted description of one offer / Unsaved Work entry."""
    offer = offer or {}
    target = offer.get("target") or {}
    props = {
        "recovery_session_id": str(offer.get("session") or "")[:64] or None,
        "crashed_app_session_id": str(offer.get("app_session_id") or "")[:64] or None,
    }
    if target:
        at = float(target.get("at") or 0.0)
        props.update({
            "candidate_kind": CANDIDATE_KINDS.get(target.get("kind"), "other"),
            "snapshot_age_s": int(max(0.0, time.time() - at)) if at else None,
            "tabs_count": len(target.get("scenes") or []),
            "attempt": len(offer.get("failed_points") or []) + 1,
            "crash_loop": bool(offer.get("loop")),
        })
    return props


def track(stage: str, offer: dict | None = None, *, surface: str = "",
          failure_category: str = "", outcome: str = "", duration_s: float | None = None,
          reshown: bool | None = None) -> None:
    """Emit ``session_recovery.<stage>``. Never raises."""
    global _last_save_point_failed
    try:
        if stage not in STAGES:
            return
        if stage == "save_point_failed":
            now = time.monotonic()
            if _last_save_point_failed and now - _last_save_point_failed < SAVE_POINT_FAILED_INTERVAL_S:
                return
            _last_save_point_failed = now
        props = offer_properties(offer) if offer is not None else {}
        if surface:
            props["surface"] = surface if surface in SURFACES else "other"
        if failure_category:
            props["failure_category"] = (failure_category if failure_category in FAILURE_CATEGORIES
                                         else "other")
        if outcome:
            props["outcome"] = outcome if outcome in OUTCOMES else "other"
        if duration_s is not None:
            props["duration_s"] = int(max(0.0, float(duration_s)))
        if reshown is not None:
            props["reshown"] = bool(reshown)
        capture(EVENT_SESSION_RECOVERY_PREFIX + stage, props)
    except Exception:  # noqa: BLE001 - telemetry never breaks recovery
        pass


def reset() -> None:
    """Test hook: forget the save-point failure rate limit."""
    global _last_save_point_failed
    _last_save_point_failed = 0.0
