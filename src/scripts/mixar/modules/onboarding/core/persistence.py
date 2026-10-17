# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding persistence

Tracks whether this device has already seen the onboarding tour — got past
its first step, or finished or exited it. Stored as a JSON file in Mixar's
user-data dir so the flag survives restarts.

The flag is per device, not per account: a guest's identity is a fresh
placeholder email, so a per-email list could never dedupe it and the tour
kept coming back. Files written before this keyed the flag by email
(``users_seen``); any entry there means the device has seen it.
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


def _read() -> dict:
    path = _seen_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("Onboarding persistence: read failed: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def has_device_seen_onboarding() -> bool:
    """True once anyone on this device has seen the tour."""
    with _LOCK:
        data = _read()
    if data.get("seen") is True:
        return True
    legacy = data.get("users_seen")
    return isinstance(legacy, list) and any(legacy)


def mark_device_seen_onboarding() -> None:
    """Record that this device has seen the tour. Idempotent."""
    path = _seen_path()
    with _LOCK:
        if _read().get("seen") is True:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"seen": True}, fh, indent=2)
        except Exception as exc:
            logger.warning("Onboarding persistence: write failed: %s", exc)
            return
    logger.info("Onboarding: marked this device as seen")
