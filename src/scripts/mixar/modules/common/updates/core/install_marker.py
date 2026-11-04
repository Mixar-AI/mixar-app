# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update-in-Progress Marker

``update-in-progress.json`` in the staging directory says "a helper is
installing an update right now". The app writes it right after spawning
the helper; the helper deletes it on every exit path, just before it
relaunches Mixar. While it is there, nothing may run from the install:

- On Windows a Mixar the user opens by hand holds files in the install
  directory (the helper's lock wait then refuses to install), and its
  update check purges the staging directory — including the helper's own
  batch file, which cmd.exe reads line by line, so the update dies half
  way with "The batch file cannot be found".
- On macOS it runs the old binary over a bundle swapped underneath it, and
  the helper's ``open`` only brings that stale instance forward.

So the startup check (:func:`check_startup`) makes such a Mixar say
"finishing an update" and quit, and :func:`staging.purge_stale` leaves
the directory alone (:func:`live_marker`).

A marker counts only while it names a LIVE helper: its PID is running,
with the creation time recorded at spawn where both can be read (Windows
``GetProcessTimes``, macOS the ``sysctl`` start time), and it is younger
than ``HELPER_MARKER_MAX_AGE_S``. Gone, a reused PID or too old is stale
and the file is deleted. One that cannot be judged — unreadable for the
moment (antivirus holding the new file), or a process lookup that raised
— blocks nothing but is kept, and keeps guarding the purge, until the
file itself is older than the age cap: deleting it would let this launch
purge the live helper's own script. The guard fails open, never destructive.

Filesystem and process lookups only — imports no ``bpy``.
"""

import json
import os
import struct
import sys
import time

from mixar.config.logging_config import get_logger

from ..constants import HELPER_MARKER_MAX_AGE_S, HELPER_MARKER_NAME

logger = get_logger(__name__)

# sysctl(CTL_KERN, KERN_PROC, KERN_PROC_PID, pid) answers a kinfo_proc
# (648 bytes on arm64/x86_64) whose first field is the start time, a
# timeval (int64 seconds, int32 microseconds); no such process answers
# zero bytes.
_CTL_KERN, _KERN_PROC, _KERN_PROC_PID = 1, 14, 1
_KINFO_PROC_BUFFER = 1024


def marker_path(directory: str) -> str:
    return os.path.join(directory, HELPER_MARKER_NAME)


def _mac_started(pid: int):
    """Start time of *pid* as ``"<seconds>.<microseconds>"``, or None.

    The kernel's own record, read without a subprocess (``ps -o lstart``
    would cost one on the startup path and only has whole seconds).
    """
    import ctypes

    mib = (ctypes.c_int * 4)(_CTL_KERN, _KERN_PROC, _KERN_PROC_PID, int(pid))
    buffer = ctypes.create_string_buffer(_KINFO_PROC_BUFFER)
    size = ctypes.c_size_t(len(buffer))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.sysctl(mib, 4, buffer, ctypes.byref(size), None, 0) != 0 or size.value < 12:
        return None
    seconds, microseconds = struct.unpack_from("=qi", buffer.raw, 0)
    return f"{seconds}.{microseconds:06d}"


def process_identity(pid: int):
    """``(alive, created)`` for *pid*; ``created`` is None when unreadable.

    Raises when the lookup itself fails — callers treat that as "not live".
    """
    pid = int(pid)
    if pid <= 0:
        return False, None
    if os.name == "nt":
        from . import win_processes

        return win_processes.process_state(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        pass  # another account's process: alive
    return True, (_mac_started(pid) if sys.platform == "darwin" else None)


def write(directory: str, helper_pid: int, target_version: str, attempt_id: str) -> bool:
    """Record the helper just spawned. Never raises; False when not written.

    Written to a temporary name and renamed over, so a reader never sees
    half a file.
    """
    try:
        _alive, created = process_identity(helper_pid)
    except Exception:  # noqa: BLE001 - age + PID still identify it
        logger.debug("Could not read the update helper's creation time", exc_info=True)
        created = None
    path = marker_path(directory)
    temporary = path + ".tmp"
    try:
        record = {
            "helper_pid": int(helper_pid),
            "helper_created": created,
            "target_version": target_version or "",
            "attempt_id": attempt_id or "",
            "written_at": time.time(),
        }
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as e:
        logger.warning("Could not write the update-in-progress marker: %s", e)
        _remove_file(temporary)
        return False
    return True


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("Could not remove %s: %s", path, e)


def remove(directory: str) -> None:
    """Delete the marker in *directory*, if any."""
    _remove_file(marker_path(directory))


def read(directory: str):
    """The marker's dict, or None when missing or unreadable."""
    try:
        with open(marker_path(directory), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _liveness(record, now=None):
    """True while *record* names a running helper started for this update,
    False when it positively does not, None when the lookup itself failed."""
    try:
        pid = int(record["helper_pid"])
        age = (time.time() if now is None else now) - float(record["written_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if abs(age) > HELPER_MARKER_MAX_AGE_S:
        return False
    try:
        alive, created = process_identity(pid)
    except Exception:  # noqa: BLE001 - unknown, not stale
        logger.debug("Could not look up update helper pid %s", pid, exc_info=True)
        return None
    if not alive:
        return False
    recorded = record.get("helper_created")
    # Both known and different: the helper is gone and its PID reused.
    return recorded is None or created is None or str(recorded) == str(created)


def is_live(record, now=None) -> bool:
    """True while *record* names a running helper started for this update."""
    return _liveness(record, now) is True


def _past_age_cap(path: str) -> bool:
    """The file itself is older than any helper could still be running."""
    try:
        return time.time() - os.stat(path).st_mtime > HELPER_MARKER_MAX_AGE_S
    except OSError:
        return False


def _judge(directory: str):
    """``(record, verdict)`` for the marker in *directory*: the verdict is
    True (live), False (stale or missing) or None (cannot be judged yet)."""
    path = marker_path(directory)
    if not os.path.lexists(path):
        return None, False
    record = read(directory)
    verdict = None if record is None else _liveness(record)
    if verdict is None and _past_age_cap(path):
        verdict = False
    return record, verdict


def live_marker(directory: str):
    """The marker in *directory* when it names a live helper, else None."""
    record, verdict = _judge(directory)
    return record if verdict is True else None


def guards_staging(directory: str) -> bool:
    """Must the staging directory be left alone? True while the marker is
    live or cannot be judged yet (its helper may well be running)."""
    return _judge(directory)[1] is not False


def check_startup(running_version: str):
    """The live marker that must stop this launch, or None.

    Deletes a stale marker on the way; keeps one it cannot judge. A marker
    whose target is the version running stops nothing and is kept: that is
    the build the helper is putting in place (it deletes the marker before
    it relaunches, so this is a belt-and-braces case — a helper slow to
    exit, or the new build opened by hand once its files are in place).
    """
    from . import installer, staging

    for directory in staging.existing_staging_dirs():
        if not os.path.lexists(marker_path(directory)):
            continue
        record, verdict = _judge(directory)
        if verdict is None:
            logger.info("Could not judge the update marker in %s - leaving it", directory)
            continue
        if verdict is False:
            logger.info("Removing stale update marker in %s", directory)
            remove(directory)
            continue
        if installer._same_version(record.get("target_version", ""), running_version):
            logger.info("Update helper for %s still running; this is that build",
                        running_version)
            continue
        return record
    return None
