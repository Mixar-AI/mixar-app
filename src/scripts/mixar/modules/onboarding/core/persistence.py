# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding persistence

Tracks which users (by email) have already completed or skipped the
onboarding tour. Stored as a JSON file in Mixar's user-data dir so
the flag survives Blender restarts and is per-machine, per-account.

The seen-list is the gate for whether the welcome card opens — a
user appears in this file once they've finished or explicitly
skipped the tour, and from then on they never see the tour again
on this machine. Different users on the same machine each see the
tour exactly once.
"""

import json
import os
import threading

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()
_FILENAME = "onboarding_seen.json"


def _data_dir() -> str:
    """Pick the same per-user data dir other Mixar modules use:
    ``bpy.utils.user_resource('DATAFILES', path='mixar')`` when
    Blender is available, else fall back to ``~/.mixar``.
    """
    try:
        path = bpy.utils.user_resource("DATAFILES", path="mixar")
        if path:
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".mixar")


def _seen_path() -> str:
    return os.path.join(_data_dir(), _FILENAME)


def _load_seen() -> set:
    """Return the set of emails that have already completed or
    skipped the onboarding tour."""
    path = _seen_path()
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return set()
        users = data.get("users_seen", [])
        if not isinstance(users, list):
            return set()
        return {str(u).strip().lower() for u in users if u}
    except Exception as exc:
        logger.warning("Onboarding persistence: read failed: %s", exc)
        return set()


def _save_seen(emails: set) -> None:
    """Write the seen-emails set back to disk. Creates the parent
    dir if it doesn't exist."""
    path = _seen_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {"users_seen": sorted(emails)}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except Exception as exc:
        logger.warning("Onboarding persistence: write failed: %s", exc)


def has_user_seen_onboarding(email: str) -> bool:
    """True if ``email`` has already completed or skipped the tour
    on this machine."""
    if not email:
        return True  # No identity → don't show.
    key = email.strip().lower()
    with _LOCK:
        seen = _load_seen()
    return key in seen


def mark_user_seen_onboarding(email: str) -> None:
    """Record ``email`` as having completed or skipped the tour.
    Idempotent — calling twice is harmless."""
    if not email:
        return
    key = email.strip().lower()
    with _LOCK:
        seen = _load_seen()
        if key in seen:
            return
        seen.add(key)
        _save_seen(seen)
    logger.info("Onboarding: marked user as seen (%s)", key)
