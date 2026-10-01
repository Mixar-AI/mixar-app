# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""On-disk store of turn checkpoints: ``~/.mixar/checkpoints/<session>/``
holds the ``.mixar`` snapshots and an ``index.json`` of records. Paths,
atomic JSON, the per-session index, listing, and the per-kind prune. The
caps live with the policy in ``turn_checkpoints``.
"""

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

_INDEX_FILENAME = "index.json"
_RECORD_VERSION = 1


# =============================================================================
# Paths and JSON
# =============================================================================

def checkpoints_root() -> str:
    """Per-user app-data dir, next to chat_history — never Blender's session
    temp dir, which is purged on exit."""
    return os.path.join(os.path.expanduser("~"), ".mixar", "checkpoints")


def _safe_id(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "")[:80] or "_nosession"


def session_dir(session_id: str) -> str:
    path = os.path.join(checkpoints_root(), _safe_id(session_id))
    os.makedirs(path, exist_ok=True)
    return path


def _index_path(session_id: str) -> str:
    return os.path.join(session_dir(session_id), _INDEX_FILENAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _order(item: dict):
    """Newest last: creation time, then the per-session sequence (several
    captures can share a timestamp)."""
    return (item.get("created_at", ""), int(item.get("seq", 0) or 0))


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


REPLACE_ATTEMPTS = 6
REPLACE_RETRY_SECONDS = 0.05


def replace_file(src: str, dst: str) -> None:
    """``os.replace`` with a short bounded retry. On Windows a file that was
    just written can be held open by an antivirus scan or an indexer for a
    moment, and the rename then fails with a sharing violation
    (``PermissionError``, WinError 32); on POSIX the first attempt is the only
    one that runs. A retry that still fails raises the last error."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_SECONDS)


def _atomic_write_json(path: str, data) -> None:
    """tmp + rename so a crash never leaves a half-written index."""
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        replace_file(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# =============================================================================
# Index
# =============================================================================

def _load_index(session_id: str) -> list:
    data = _read_json(_index_path(session_id))
    items = data.get("checkpoints") if isinstance(data, dict) else None
    return [i for i in (items or []) if isinstance(i, dict) and i.get("id")]


def _write_index(session_id: str, items: list) -> None:
    _atomic_write_json(_index_path(session_id), {"version": _RECORD_VERSION, "checkpoints": items})


def _file_path(record: dict) -> str:
    return os.path.join(session_dir(record.get("session_id", "")), record.get("file", ""))


def list_checkpoints(session_id: str) -> list:
    """Restorable checkpoints of a session, newest first."""
    if not session_id:
        return []
    items = [i for i in _load_index(session_id) if os.path.isfile(_file_path(i))]
    return sorted(items, key=_order, reverse=True)


_has_cache = {}


def has_checkpoints(session_id: str) -> bool:
    """Header-draw cheap: one stat of the index per draw, re-read on change."""
    if not session_id:
        return False
    path = os.path.join(checkpoints_root(), _safe_id(session_id), _INDEX_FILENAME)
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        _has_cache.pop(session_id, None)
        return False
    cached = _has_cache.get(session_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    value = bool(list_checkpoints(session_id))
    _has_cache[session_id] = (stamp, value)
    return value


def get_checkpoint(session_id: str, checkpoint_id: str):
    for item in _load_index(session_id):
        if item.get("id") == checkpoint_id:
            return item
    return None


def _remove_files(stale: list, kept: list) -> None:
    """Delete the files of dropped records unless a kept record shares them."""
    referenced = {i.get("file") for i in kept}
    for record in stale:
        if record.get("file") in referenced:
            continue
        try:
            os.remove(_file_path(record))
        except OSError:
            pass


def prune(items: list, *, max_turns: int, max_safety: int, protect_id: str = "") -> list:
    """Keep the newest records per kind; drop files nothing references.

    Turn snapshots and safety copies have separate caps: a busy chat must not
    push out the copy that is an artist's only way back from a restore.
    ``protect_id`` survives its cap this once: the record a jump is about to
    read must not be evicted by the copy that jump captures first."""
    items = sorted(items, key=_order)
    safety = [i for i in items if i.get("kind") == "safety"]
    tips = [i for i in items if i.get("kind") == "tip"]
    turns = [i for i in items if i.get("kind", "turn") == "turn"]
    kept = turns[-max_turns:] + tips[-1:] + safety[-max_safety:]
    stale = turns[:-max_turns] + tips[:-1] + safety[:-max_safety]
    protected = [i for i in stale if protect_id and i.get("id") == protect_id]
    kept = sorted(kept + protected, key=_order)
    _remove_files([i for i in stale if i not in protected], kept)
    return kept


def _update(session_id: str, checkpoint_id: str, **changes) -> None:
    items = _load_index(session_id)
    for item in items:
        if item.get("id") == checkpoint_id:
            item.update(changes)
    _write_index(session_id, items)
