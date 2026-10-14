# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Operation history hygiene: one folder per scene across undo, a prune that stays off
the main thread and rewrites nothing that did not change, leaked undo-only sessions gone.

Found through the stall monitor: 13,658 session folders (11,619 opened by an undo
marker) rewritten in full by the daily prune inside the first agent turn, 5.4 s on the
main thread.
"""

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

from mixar.modules.operation_history import constants as C
from mixar.modules.operation_history.core import scene_key, store
from mixar.modules.operation_history.core.record import build_manual_record


@pytest.fixture
def history_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(C.ENV_BASE_DIR, str(tmp_path))
    store.reset_cache()
    scene_key.forget_all()
    yield tmp_path
    store.reset_cache()
    scene_key.forget_all()


def _write(sid, records, history_dir):
    d = history_dir / sid
    (d / "scripts").mkdir(parents=True)
    (d / "operations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return d


def _rec(ts, category="OBJECT", seq=1, script=None):
    rec = {"category": category, "ts": ts, "seq": seq, "op_idname": "x"}
    if script:
        rec["script_file"] = f"scripts/{script}"
    return rec


def test_scene_id_survives_undo(history_dir):
    scene = SimpleNamespace(name="Scene", session_uid=11, mixar_op_history_id="")
    first = scene_key.get_scene_history_id(scene)
    assert first and getattr(scene, C.SCENE_HISTORY_ID_PROP) == first
    setattr(scene, C.SCENE_HISTORY_ID_PROP, "")          # memfile undo blanked the property
    assert scene_key.get_scene_history_id(scene) == first
    assert getattr(scene, C.SCENE_HISTORY_ID_PROP) == first   # written back for the next save
    other = SimpleNamespace(name="Scene.001", session_uid=12, mixar_op_history_id="")
    assert scene_key.get_scene_history_id(other) != first
    scene_key.forget_all()                                 # a new file: new datablocks
    setattr(scene, C.SCENE_HISTORY_ID_PROP, "")
    assert scene_key.get_scene_history_id(scene) != first


def test_new_scene_under_a_dead_scenes_name_gets_its_own_id(history_dir):
    """Review finding 4: memory keyed by name gave a new "Scene.001" the history
    of the deleted tab that had that name, and a rename shared one folder."""
    dead = SimpleNamespace(name="Scene.001", session_uid=21, mixar_op_history_id="")
    dead_id = scene_key.get_scene_history_id(dead)
    reborn = SimpleNamespace(name="Scene.001", session_uid=22, mixar_op_history_id="")
    assert scene_key.get_scene_history_id(reborn) != dead_id
    renamed = SimpleNamespace(name="Shot", session_uid=21, mixar_op_history_id="")
    assert scene_key.get_scene_history_id(renamed) == dead_id     # same datablock, renamed
    fresh = SimpleNamespace(name="Scene", session_uid=23, mixar_op_history_id="")
    assert scene_key.get_scene_history_id(fresh) != dead_id


def test_prune_leaves_fresh_sessions_untouched(history_dir):
    now = time.time()
    d = _write("fresh", [_rec(now - 60, seq=1), _rec(now - 30, category=C.CAT_UNDO, seq=2)], history_dir)
    before = os.stat(d / "operations.jsonl").st_mtime_ns
    stats = store.cleanup_expired(now=now)
    assert stats == {"sessions": 1, "rewritten": 0, "removed_sessions": 0, "removed_records": 0}
    assert os.stat(d / "operations.jsonl").st_mtime_ns == before


def test_prune_drops_expired_records_and_scripts_only(history_dir):
    now = time.time()
    old = now - (C.CLEANUP_MAX_AGE_DAYS + 1) * 86400
    d = _write("mixed", [_rec(old, seq=1, script="0001_x.py"), _rec(now - 10, seq=2, script="0002_x.py")], history_dir)
    (d / "scripts/0001_x.py").write_text("old")
    (d / "scripts/0002_x.py").write_text("new")
    stats = store.cleanup_expired(now=now)
    assert stats["rewritten"] == 1 and stats["removed_records"] == 1
    kept = [json.loads(l) for l in (d / "operations.jsonl").read_text().splitlines()]
    assert [r["seq"] for r in kept] == [2]
    assert not (d / "scripts/0001_x.py").exists() and (d / "scripts/0002_x.py").exists()


def test_prune_removes_leaked_undo_only_sessions(history_dir):
    now = time.time()
    stale = now - 2 * 86400
    _write("leak", [_rec(stale, category=C.CAT_UNDO)], history_dir)
    _write("leak_redo", [_rec(stale, category=C.CAT_UNDO), _rec(stale + 1, category=C.CAT_UNDO, seq=2)], history_dir)
    _write("recent_undo", [_rec(now - 3600, category=C.CAT_UNDO)], history_dir)      # may still get real ops
    _write("real", [_rec(stale, category=C.CAT_UNDO), _rec(stale + 5, category="OBJECT", seq=2)], history_dir)
    stats = store.cleanup_expired(now=now)
    assert stats["removed_sessions"] == 2 and stats["removed_records"] == 3
    assert sorted(p.name for p in history_dir.iterdir()) == ["real", "recent_undo"]


def test_append_schedules_the_prune_on_a_worker_thread(history_dir, monkeypatch):
    seen = {}
    monkeypatch.setattr(store, "cleanup_expired", lambda: seen.setdefault("thread", threading.current_thread()))
    rec = build_manual_record(scene_delta=None, label="t", category="OBJECT", session_id="s1")
    store.append_operation(rec)
    store._cleanup_thread.join(5)
    assert seen["thread"] is not threading.main_thread()
    assert seen["thread"].name == "mixar-operation-history-cleanup"
    # Only once per day: a second append does not start another.
    rec2 = build_manual_record(scene_delta=None, label="t2", category="OBJECT", session_id="s1")
    seen.clear()
    store.append_operation(rec2)
    assert "thread" not in seen
    lines = (history_dir / "s1" / "operations.jsonl").read_text().splitlines()
    assert [json.loads(l)["seq"] for l in lines] == [1, 2]
