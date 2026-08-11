# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Post-output rejection telemetry.

A generation (or agent) output "lands" in the scene; if the user undoes or
deletes it within ``REJECTION_WINDOW_SECONDS`` the output was rejected.
Landings are tracked in-process only; each landing produces at most one
``generation.rejected`` event.
"""

from __future__ import annotations

import time

from .capture import capture
from .constants import EVENT_GENERATION_REJECTED, REJECTION_WINDOW_SECONDS

# Entries: (monotonic timestamp, source, frozenset of object session_uids | None)
_landings: list[tuple[float, str, frozenset | None]] = []


def reset_rejection_state() -> None:
    """Test hook."""
    _landings.clear()


def _prune(now: float) -> None:
    _landings[:] = [
        entry for entry in _landings
        if now - entry[0] <= REJECTION_WINDOW_SECONDS
    ]


def note_output_landed(source: str, object_uids=None) -> None:
    """Record that an output arrived. ``source`` is "generation" | "agent"."""
    try:
        now = time.monotonic()
        _prune(now)
        uids = frozenset(object_uids) if object_uids else None
        _landings.append((now, str(source), uids))
    except Exception:
        pass


def has_tracked_uids() -> bool:
    """Cheap gate for the poll: any active landing tracking object uids?"""
    return any(entry[2] for entry in _landings)


def on_undo() -> None:
    """Undo within the window rejects the MOST RECENT landing, then clears."""
    try:
        now = time.monotonic()
        _prune(now)
        if not _landings:
            return
        landed_at, source, _uids = _landings[-1]
        _landings.clear()
        capture(EVENT_GENERATION_REJECTED, {
            "trigger": "undo",
            "source": source,
            "seconds_since_output": int(now - landed_at),
        })
    except Exception:
        pass


def check_deleted_objects() -> None:
    """Poll hook: a tracked object vanishing from bpy.data means deletion.

    Skips entirely (no bpy access) unless a landing with uids is active.
    """
    try:
        if not has_tracked_uids():
            return
        now = time.monotonic()
        _prune(now)
        tracked = [entry for entry in _landings if entry[2]]
        if not tracked:
            return
        import bpy
        live = {
            getattr(obj, "session_uid", None)
            for obj in getattr(bpy.data, "objects", ()) or ()
        }
        for entry in tracked:
            landed_at, _source, uids = entry
            if any(uid not in live for uid in uids):
                try:
                    _landings.remove(entry)
                except ValueError:
                    pass
                capture(EVENT_GENERATION_REJECTED, {
                    "trigger": "delete",
                    "source": "generation",
                    "seconds_since_output": int(now - landed_at),
                })
    except Exception:
        pass
