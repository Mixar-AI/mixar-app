# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-recovery telemetry (``session_recovery``).

The funnel from "Mixar died" to "the work is back": an unclean exit found at
startup, a restore available and offered, the user's choice, the file read
and the follow-up (generations re-attached, the document retitled). Plus a
rate-limited signal when a save point could not be written.

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
})
# The journal's candidate kinds, as analysis reads them.
CANDIDATE_KINDS = {
    "save_point": "save_point", "inherited": "save_point", "autosave": "autosave",
    "project": "project", "snapshot": "turn_checkpoint",
}
SURFACES = frozenset({"splash", "dialog", "file_menu"})
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
          failure_category: str = "") -> None:
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
        capture(EVENT_SESSION_RECOVERY_PREFIX + stage, props)
    except Exception:  # noqa: BLE001 - telemetry never breaks recovery
        pass


def reset() -> None:
    """Test hook: forget the save-point failure rate limit."""
    global _last_save_point_failed
    _last_save_point_failed = 0.0
