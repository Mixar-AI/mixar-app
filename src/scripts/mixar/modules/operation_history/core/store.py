# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-session local-directory store: operations.jsonl + scripts/. Trusted (full I/O).

Never raises into callers — capture/recording is best-effort and must never break a
script execution or a UI action.
"""

import json
import os
import re
import shutil
import tempfile
import threading
import time
from typing import Optional

from ..constants import (
    CAT_UNDO, CLEANUP_MAX_AGE_DAYS, DEFAULT_DATA_SUBDIR, ENV_BASE_DIR, MAX_LIST_RESULTS,
    MAX_SCRIPT_CHARS, MODULE_DIR_NAME, NO_SESSION, OPERATIONS_FILE, SCRIPTS_SUBDIR,
    UNDO_ONLY_MAX_AGE_DAYS,
)
from .record import OperationRecord, build_manual_record

_lock = threading.Lock()
_seq_cache: dict = {}
_last_cleanup_day: Optional[int] = None
_cleanup_thread: Optional[threading.Thread] = None


def _base_dir() -> str:
    override = os.environ.get(ENV_BASE_DIR)
    if override:
        return override
    try:
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            return os.path.join(home, DEFAULT_DATA_SUBDIR, MODULE_DIR_NAME)
    except Exception:
        pass
    return os.path.join(tempfile.gettempdir(), MODULE_DIR_NAME)


def _safe(s: Optional[str]) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s or NO_SESSION)[:128] or NO_SESSION


def session_dir(session_id: str) -> str:
    return os.path.join(_base_dir(), _safe(session_id))


def _ops_path(session_id: str) -> str:
    return os.path.join(session_dir(session_id), OPERATIONS_FILE)


def _ensure_dirs(session_id: str) -> str:
    d = session_dir(session_id)
    os.makedirs(os.path.join(d, SCRIPTS_SUBDIR), exist_ok=True)
    return d


def _script_path_for_record(session_id: str, rec: dict) -> Optional[str]:
    script_file = rec.get("script_file")
    if not script_file or os.path.isabs(script_file):
        return None
    normalized = os.path.normpath(script_file)
    if normalized == ".." or normalized.startswith(".." + os.sep):
        return None
    return os.path.join(session_dir(session_id), normalized)


def _session_ids() -> list:
    base = _base_dir()
    if not os.path.isdir(base):
        return []
    try:
        return [
            name for name in os.listdir(base)
            if os.path.isdir(os.path.join(base, name))
        ]
    except Exception:
        return []


def _read_records(ops_path: str) -> list:
    """(raw_line, parsed_or_None) per non-empty line; a torn line parses to None."""
    rows = []
    with open(ops_path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                rows.append((raw, json.loads(raw)))
            except Exception:
                rows.append((raw, None))
    return rows


def cleanup_expired(max_age_days: int = CLEANUP_MAX_AGE_DAYS, *, now: Optional[float] = None,
                    undo_only_max_age_days: float = UNDO_ONLY_MAX_AGE_DAYS) -> dict:
    """Prune operation records and saved scripts older than ``max_age_days``.

    A session whose records are all undo/redo markers older than ``undo_only_max_age_days``
    is removed whole: it describes nothing (every undo in a fresh scene used to open one).
    A file is rewritten only when a record was dropped, so an up-to-date store costs one
    read per session. Safe to run off the main thread: each session's rewrite holds the
    store lock, and nothing here touches bpy. Uses JSONL record timestamps rather than
    platform-specific birth times, so it behaves consistently on macOS and Windows.
    Best-effort: failures are ignored by design. Returns counts for tests and logs.
    """
    stats = {"sessions": 0, "rewritten": 0, "removed_sessions": 0, "removed_records": 0}
    if max_age_days <= 0:
        return stats
    now = time.time() if now is None else now
    cutoff = now - (max_age_days * 86400)
    undo_cutoff = now - (undo_only_max_age_days * 86400)
    for sid in _session_ids():
        ops_path = _ops_path(sid)
        if not os.path.isfile(ops_path):
            continue
        stats["sessions"] += 1
        try:
            with _lock:
                rows = _read_records(ops_path)
                parsed = [rec for _raw, rec in rows if rec is not None]
                undo_only = bool(parsed) and all(
                    rec.get("category") == CAT_UNDO for rec in parsed)
                newest = max((float(rec.get("ts", 0) or 0) for rec in parsed), default=0.0)
                if undo_only and newest < undo_cutoff:
                    shutil.rmtree(session_dir(sid), ignore_errors=True)
                    _seq_cache.pop(sid, None)
                    stats["removed_sessions"] += 1
                    stats["removed_records"] += len(parsed)
                    continue
                kept = []
                removed_scripts = []
                for raw, rec in rows:
                    if rec is not None and float(rec.get("ts", 0) or 0) < cutoff:
                        script_path = _script_path_for_record(sid, rec)
                        if script_path:
                            removed_scripts.append(script_path)
                        stats["removed_records"] += 1
                    else:
                        kept.append(raw)
                if len(kept) == len(rows):
                    continue
                if kept:
                    tmp_path = ops_path + ".tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(kept) + "\n")
                    os.replace(tmp_path, ops_path)
                    stats["rewritten"] += 1
                else:
                    shutil.rmtree(session_dir(sid), ignore_errors=True)
                    stats["removed_sessions"] += 1
                _seq_cache.pop(sid, None)
            for script_path in removed_scripts:
                try:
                    os.remove(script_path)
                except Exception:
                    pass
        except Exception:
            pass
    return stats


def _schedule_cleanup_once_per_day() -> None:
    """Run the prune on a daemon thread the first time the store is written each day.

    It used to run inline in the first append of the day, which on the main thread held
    the UI for 5.4 s with 13,658 sessions on disk.
    """
    global _last_cleanup_day, _cleanup_thread
    day = int(time.time() // 86400)
    if _last_cleanup_day == day:
        return
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return
    _last_cleanup_day = day
    _cleanup_thread = threading.Thread(
        target=cleanup_expired, name="mixar-operation-history-cleanup", daemon=True)
    _cleanup_thread.start()


def _next_seq(session_id: str) -> int:
    if session_id not in _seq_cache:
        # Resume from the highest retained seq, NOT the line count: after
        # cleanup_expired prunes old records the file has fewer lines than
        # the max seq, so counting would hand out numbers that collide with
        # retained records and fall below callers' since_seq high-watermark
        # (silently hiding every new operation from pagination).
        n = 0
        p = _ops_path(session_id)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            seq = int(json.loads(line).get("seq", 0) or 0)
                        except Exception:
                            continue
                        if seq > n:
                            n = seq
            except Exception:
                n = 0
        _seq_cache[session_id] = n
    _seq_cache[session_id] += 1
    return _seq_cache[session_id]


def append_operation(rec: OperationRecord, script_text: Optional[str] = None) -> OperationRecord:
    try:
        _schedule_cleanup_once_per_day()
        with _lock:
            sid = rec.session_id or NO_SESSION
            rec.session_id = sid
            _ensure_dirs(sid)
            rec.seq = _next_seq(sid)
            if script_text is not None:
                fname = "{:04d}_{}.py".format(rec.seq, _safe(rec.tool_name or "script"))
                with open(os.path.join(session_dir(sid), SCRIPTS_SUBDIR, fname),
                          "w", encoding="utf-8") as f:
                    f.write(script_text)
                rec.script_file = "{}/{}".format(SCRIPTS_SUBDIR, fname)
            with open(_ops_path(sid), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
    except Exception:
        pass  # best-effort
    return rec


def read_operations(session_id: str, *, limit: int = MAX_LIST_RESULTS, source=None,
                    kind=None, category=None, object_name=None, since_seq=None) -> list:
    p = _ops_path(session_id)
    rows: list = []
    if not os.path.isfile(p):
        return rows
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if source and rec.get("source") != source:
                    continue
                if kind and rec.get("kind") != kind:
                    continue
                if category and rec.get("category") != category:
                    continue
                if since_seq is not None and rec.get("seq", 0) <= since_seq:
                    continue
                if object_name:
                    aff = rec.get("affected") or {}
                    delta = rec.get("scene_delta") or {}
                    names = set(aff.get("objects", []) or [])
                    for k in ("created", "modified", "deleted"):
                        names |= set(delta.get(k, []) or [])
                    if object_name not in names:
                        continue
                rows.append(rec)
    except Exception:
        return rows
    if limit and limit > 0:
        return rows[-limit:]
    return rows


def read_script(session_id: str, seq=None, op_id=None) -> Optional[str]:
    for rec in read_operations(session_id, limit=0):
        if (seq is not None and rec.get("seq") == seq) or (op_id is not None and rec.get("id") == op_id):
            sf = rec.get("script_file")
            if not sf:
                return None
            sp = os.path.join(session_dir(session_id), sf)
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    return f.read()[:MAX_SCRIPT_CHARS]
            except Exception:
                return None
    return None


def record_operation(session_id: str, label: str, category: str = "OTHER", *,
                     op_idname=None, affected=None, scene_delta=None, instance_id="") -> OperationRecord:
    """Public emit API for other modules (e.g. paint) to log a semantic manual op."""
    rec = build_manual_record(
        scene_delta=scene_delta, op_idname=op_idname, label=label, category=category,
        affected=affected, session_id=session_id, instance_id=instance_id,
    )
    return append_operation(rec)


def reset_cache() -> None:
    global _last_cleanup_day
    _seq_cache.clear()
    _last_cleanup_day = None
