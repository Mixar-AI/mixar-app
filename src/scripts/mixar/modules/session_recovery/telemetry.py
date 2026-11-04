# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recovery telemetry hooks: ``session_recovery.<stage>`` events.

The allowlist and the consent/auth gate are the shared analytics helper's
(``common/analytics/recovery_events.py``); this module only decides when.
Every function swallows every error: telemetry never breaks recovery.
"""

from __future__ import annotations

import os

from . import journal

_offered: set = set()


def track(stage: str, offer: dict | None = None, **props) -> None:
    try:
        from mixar.modules.common.analytics.recovery_events import track as _track
        _track(stage, offer, **props)
    except Exception:  # noqa: BLE001
        pass


def app_session_id() -> str:
    try:
        from mixar.modules.common.analytics.capture import app_session_id as _id
        return _id()
    except Exception:  # noqa: BLE001
        return ""


def report_startup(offer: dict | None, current: dict | None) -> None:
    """Each crashed session once (its manifest remembers it was reported),
    then what this launch offers (``current``, every launch it is offered)."""
    try:
        offer = offer or {}
        crashed = ([offer] if offer.get("target") else []) + list(offer.get("older") or [])
        crashed += [{"session": os.path.basename(d), "dir": d} for d in offer.get("debris") or []]
        for entry in crashed:
            directory = entry.get("dir") or ""
            if directory and (journal.read_manifest(directory) or {}).get("unclean_exit_reported"):
                continue
            track("unclean_exit_detected", entry)
            if directory:
                journal.update_manifest(directory, unclean_exit_reported=True)
        if current is not None:
            track("available", current)
    except Exception:  # noqa: BLE001
        pass


def note_offered(surface: str, offer: dict | None) -> None:
    """The restore question (or the Unsaved Work list) is on screen: once per
    surface per launch. Called from draw code, so the event goes out on the
    next timer tick, never inside the draw."""
    try:
        if surface in _offered:
            return
        _offered.add(surface)
        import bpy

        def _send():
            track("offered", offer, surface=surface)
            return None
        bpy.app.timers.register(_send, first_interval=0.0)
    except Exception:  # noqa: BLE001
        pass
