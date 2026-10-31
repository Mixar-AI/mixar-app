# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The recovery journal: one directory per running Mixar, on disk.

``<profile>/datafiles/mixar/recovery/<session>/`` holds ``manifest.json`` (what this launch
has to recover from), the save points (``sp-<seq>.mixar``) and ``lock``.
The lock is held for the whole life of the process; the OS drops it when the
process dies, however it dies, so a free lock on a directory whose manifest
says ``clean_exit: false`` is a session that crashed. A clean quit deletes
the directory.

No bpy here: everything is plain files, so the restore decision and the
crash-loop guard are unit-tested without Blender.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid

MANIFEST = "manifest.json"
LOCK = "lock"
VERSION = 1
KEEP_SAVE_POINTS = 3
KEEP_SNAPSHOTS = 3
MAX_AGE_S = 14 * 24 * 3600          # any dead session older than this is pruned
DISMISSED_KEEP_S = 7 * 24 * 3600    # a resolved session's files stay this long


def recovery_root() -> str:
    """Fallback when the profile's data dir is unavailable (``runtime`` uses
    ``DATAFILES/mixar/recovery``); never Blender's session temp dir, which a
    clean quit purges."""
    return os.path.join(os.path.expanduser("~"), ".mixar", "recovery")


def new_session_id(now: float, pid: int) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now))
    return f"{stamp}-{pid}-{uuid.uuid4().hex[:6]}"


# =============================================================================
# Files
# =============================================================================

def read_manifest(directory: str):
    """The manifest, or None when it is missing or unreadable."""
    try:
        with open(os.path.join(directory, MANIFEST), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_manifest(directory: str, data: dict) -> None:
    """tmp + fsync + rename: a crash mid-write never leaves half a manifest."""
    path = os.path.join(directory, MANIFEST)
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def update_manifest(directory: str, **changes) -> dict | None:
    """Read, change, write. ``None`` values delete the key. Returns the result."""
    data = read_manifest(directory)
    if data is None:
        return None
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    write_manifest(directory, data)
    return data


def move_file(src: str, dst: str) -> None:
    """Rename when possible (same volume, instant); copy across volumes."""
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# =============================================================================
# Liveness lock
# =============================================================================

def _lock_fd(fd: int) -> bool:
    """Take an exclusive non-blocking lock on ``fd``; False when held."""
    if os.name == "nt":
        import msvcrt
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_fd(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def acquire_lock(directory: str):
    """Hold this session's lock; returns the fd to keep open, or None."""
    path = os.path.join(directory, LOCK)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if os.name == "nt" and os.fstat(fd).st_size == 0:
        os.write(fd, b"\0")
    if not _lock_fd(fd):
        os.close(fd)
        return None
    return fd


def is_locked(directory: str) -> bool:
    """True while the process that owns ``directory`` is alive."""
    path = os.path.join(directory, LOCK)
    if not os.path.isfile(path):
        return False
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        if _lock_fd(fd):
            _unlock_fd(fd)
            return False
        return True
    finally:
        os.close(fd)


# =============================================================================
# Listing and pruning
# =============================================================================

def list_sessions(root: str, alive=is_locked) -> list:
    """Every session directory with its manifest and liveness, sorted by name."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    sessions = []
    for name in names:
        directory = os.path.join(root, name)
        if not os.path.isdir(directory):
            continue
        manifest = read_manifest(directory)
        if manifest is None:
            continue
        manifest = dict(manifest)
        manifest["dir"] = directory
        manifest["session"] = manifest.get("session") or name
        manifest["alive"] = bool(alive(directory))
        sessions.append(manifest)
    return sessions


def prune(root: str, now: float, keep=(), alive=is_locked) -> list:
    """Delete dead session directories past their keep time; returns them."""
    removed = []
    try:
        names = os.listdir(root)
    except OSError:
        return removed
    for name in names:
        directory = os.path.join(root, name)
        if name in keep or not os.path.isdir(directory) or alive(directory):
            continue
        manifest = read_manifest(directory) or {}
        started = float(manifest.get("started_at") or 0.0)
        if not started:
            try:
                started = os.path.getmtime(directory)
            except OSError:
                continue
        age = now - started
        resolved_at = float(manifest.get("resolved_at") or 0.0)
        if age > MAX_AGE_S or (manifest.get("resolved") and now - resolved_at > DISMISSED_KEEP_S):
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory)
    return removed


# =============================================================================
# The running session's journal
# =============================================================================

class Journal:
    """The manifest of THIS launch, kept in step with what is on disk."""

    def __init__(self, root: str, pid: int, app_version: str = "", now: float | None = None,
                 session: str = ""):
        now = time.time() if now is None else now
        self.root = root
        self.session = session or new_session_id(now, pid)
        self.dir = os.path.join(root, self.session)
        os.makedirs(self.dir, exist_ok=True)
        self._lock_fd = acquire_lock(self.dir)
        self.data = {
            "version": VERSION,
            "session": self.session,
            "pid": pid,
            "started_at": now,
            "app_version": app_version,
            "clean_exit": False,
            "document_path": "",
            "project_saved": None,
            "save_points": [],
            "snapshots": [],
            "inherited_points": [],
            "failed_points": [],
        }
        self.flush()

    # -- persistence -------------------------------------------------------
    def flush(self) -> None:
        write_manifest(self.dir, self.data)

    @property
    def seq(self) -> int:
        return max((int(p.get("seq", 0)) for p in self.data["save_points"]), default=0)

    # -- save points ---------------------------------------------------------
    def add_save_point(self, src: str, *, now: float, reason: str, cost_s: float,
                       original_path: str, scenes=(), agent_scenes=(), jobs=()) -> dict:
        """Move the freshly written file in as the newest save point."""
        seq = self.seq + 1
        filename = f"sp-{seq}.mixar"
        dst = os.path.join(self.dir, filename)
        move_file(src, dst)
        record = {
            "file": dst,
            "seq": seq,
            "at": now,
            "reason": reason,
            "cost_s": round(float(cost_s), 4),
            "bytes": os.path.getsize(dst),
            "original_path": original_path or "",
            "scenes": list(scenes),
            "agent_scenes": list(agent_scenes),
            "jobs": list(jobs),
        }
        points = self.data["save_points"] + [record]
        for old in points[:-KEEP_SAVE_POINTS]:
            _remove(old["file"])
        self.data["save_points"] = points[-KEEP_SAVE_POINTS:]
        inherited = self.data.get("inherited_points") or []
        self.data["inherited_points"] = []
        self.flush()
        for point in inherited:
            # Our own save point now covers the restored document: the session
            # it came from is no longer needed as a fallback.
            source = point.get("source_dir") or ""
            if source and os.path.isdir(source) and os.path.dirname(source) == self.root:
                shutil.rmtree(source, ignore_errors=True)
        return record

    def add_snapshot(self, path: str, *, now: float, original_path: str) -> None:
        """A turn-checkpoint file: a free, older candidate (never copied)."""
        snaps = [s for s in self.data["snapshots"] if s.get("file") != path]
        snaps.append({"file": path, "at": now, "original_path": original_path or ""})
        self.data["snapshots"] = snaps[-KEEP_SNAPSHOTS:]
        self.flush()

    def note_user_save(self, path: str, *, now: float) -> None:
        """The artist saved: the project file is now the newest state."""
        self.data["project_saved"] = {"path": path, "at": now}
        self.data["document_path"] = path
        for point in self.data["save_points"]:
            _remove(point["file"])
        self.data["save_points"] = []
        self.flush()

    def reset_document(self, path: str) -> None:
        """Another file was opened: what we held belonged to the one before."""
        for point in self.data["save_points"]:
            _remove(point["file"])
        self.data.update(document_path=path or "", project_saved=None,
                         save_points=[], snapshots=[], inherited_points=[])
        self.flush()

    def set_inherited(self, points: list) -> None:
        self.data["inherited_points"] = list(points)
        self.flush()

    def set_fields(self, **fields) -> None:
        self.data.update(fields)
        self.flush()

    # -- exit -------------------------------------------------------------------
    def close_clean(self) -> None:
        """Clean quit: nothing to recover, so nothing is kept."""
        inherited = self.data.get("inherited_points") or []
        if self._lock_fd is not None:
            _unlock_fd(self._lock_fd)
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        shutil.rmtree(self.dir, ignore_errors=True)
        for point in inherited:
            source = point.get("source_dir") or ""
            if source and os.path.isdir(source) and os.path.dirname(source) == self.root:
                shutil.rmtree(source, ignore_errors=True)
