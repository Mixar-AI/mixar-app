# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk budget for turn checkpoints: retiring whole session directories.

Per-session pruning alone bounds one chat at ``MAX_PER_SESSION`` snapshots,
but nothing else ever retired a session DIRECTORY, and each snapshot is a
full copy of the document. Same shape as operation_history's cleanup: an
age cutoff, a count cap, and rmtree of whatever falls outside them. The
caller (``turn_checkpoints.prune_sessions``) supplies the root and the
limits so this module owns no paths of its own.
"""

import os
import shutil
import time

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _session_mtime(path: str) -> float:
    """Newest mtime in the directory: an active session keeps being written."""
    newest = 0.0
    try:
        newest = os.path.getmtime(path)
        for name in os.listdir(path):
            try:
                newest = max(newest, os.path.getmtime(os.path.join(path, name)))
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _live_document_dir(root: str) -> str:
    """The session directory holding the OPEN document, if it lives under root.

    Older builds parked a restored UNTITLED project at <session>/working.mixar;
    a document opened from such a file still lives under root, and retiring its
    directory would take the open document with it. Protect it by where the
    document actually is, not by which session id happens to be current."""
    try:
        import bpy
        path = bpy.data.filepath or ""
        if not path:
            return ""
        parent = os.path.dirname(os.path.abspath(path))
        if os.path.normcase(os.path.dirname(parent)) != os.path.normcase(os.path.abspath(root)):
            return ""
        return os.path.basename(parent)
    except Exception:  # noqa: BLE001 -- housekeeping never blocks a capture
        return ""


def prune_sessions(root: str, keep: str, *, max_age_days: int, max_sessions: int) -> int:
    """Retire whole session directories under ``root``: older than
    ``max_age_days``, or outside the newest ``max_sessions``. ``keep`` is the
    live session's directory name, never a candidate. Returns how many were
    removed. Best effort — never raises into a capture."""
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return 0
    protected = {n for n in (keep, _live_document_dir(root)) if n}
    aged = sorted(
        ((n, _session_mtime(os.path.join(root, n))) for n in names if n not in protected),
        key=lambda pair: pair[1], reverse=True,
    )
    cutoff = time.time() - max_age_days * 86400.0
    # A protected session occupies a slot only once it actually has a directory --
    # reserving one for a session that has not written yet would retire an extra
    # candidate for nothing.
    budget = max(0, max_sessions - len(protected & set(names)))
    removed = 0
    for index, (name, mtime) in enumerate(aged):
        if index < budget and mtime >= cutoff:
            continue
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)
        removed += 1
    if removed:
        logger.info(f"Turn checkpoints: retired {removed} stale session director"
                    f"{'y' if removed == 1 else 'ies'}")
    return removed
