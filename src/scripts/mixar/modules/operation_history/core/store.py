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
import tempfile
import threading
from typing import Optional

from ..constants import (
    DEFAULT_DATA_SUBDIR, ENV_BASE_DIR, MAX_LIST_RESULTS, MAX_SCRIPT_CHARS,
    MODULE_DIR_NAME, NO_SESSION, OPERATIONS_FILE, SCRIPTS_SUBDIR,
)
from .record import OperationRecord, build_manual_record

_lock = threading.Lock()
_seq_cache: dict = {}


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


def _next_seq(session_id: str) -> int:
    if session_id not in _seq_cache:
        n = 0
        p = _ops_path(session_id)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    n = sum(1 for line in f if line.strip())
            except Exception:
                n = 0
        _seq_cache[session_id] = n
    _seq_cache[session_id] += 1
    return _seq_cache[session_id]


def append_operation(rec: OperationRecord, script_text: Optional[str] = None) -> OperationRecord:
    try:
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
    _seq_cache.clear()
