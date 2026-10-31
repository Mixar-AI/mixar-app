# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-safe sessions: the journal, the restore decision, the crash-loop
guard, the save-point scheduler and the generation records."""

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from enum import Enum

import pytest

from mixar.modules.session_recovery import decision, jobs, journal
from mixar.modules.session_recovery.scheduler import Policy, SavePointScheduler

NOW = 1_800_000_000.0


def _file(path, mtime=None, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return str(path)


def _session(tmp_path, name, *, pid=100, started=NOW - 3600, alive=False, **fields):
    directory = tmp_path / "recovery" / name
    directory.mkdir(parents=True)
    data = {"version": 1, "session": name, "pid": pid, "started_at": started,
            "clean_exit": False, "document_path": "", "project_saved": None,
            "save_points": [], "snapshots": [], "inherited_points": [], "failed_points": []}
    data.update(fields)
    journal.write_manifest(str(directory), data)
    return dict(data, dir=str(directory), alive=alive)


def _point(tmp_path, session, seq, at, **extra):
    path = _file(tmp_path / "recovery" / session / f"sp-{seq}.mixar")
    return dict({"file": path, "seq": seq, "at": at, "reason": "agent_script",
                 "original_path": "", "scenes": ["Scene"], "agent_scenes": [], "jobs": []}, **extra)


# =============================================================================
# Journal
# =============================================================================

def test_journal_files_save_points_and_keeps_the_newest_three(tmp_path):
    jr = journal.Journal(str(tmp_path / "recovery"), pid=42, now=NOW)
    for i in range(5):
        src = _file(tmp_path / "tmp" / f"{i}_autosave.mixar")
        jr.add_save_point(src, now=NOW + i, reason="timer", cost_s=0.25,
                          original_path="/p/scene.mixar", scenes=["A", "B"])
        assert not os.path.exists(src)  # moved, not copied
    points = journal.read_manifest(jr.dir)["save_points"]
    assert [p["seq"] for p in points] == [3, 4, 5]
    assert sorted(f for f in os.listdir(jr.dir) if f.endswith(".mixar")) == [
        "sp-3.mixar", "sp-4.mixar", "sp-5.mixar"]
    assert points[-1]["scenes"] == ["A", "B"] and points[-1]["cost_s"] == 0.25


def test_a_user_save_drops_the_older_save_points(tmp_path):
    jr = journal.Journal(str(tmp_path / "recovery"), pid=42, now=NOW)
    jr.add_save_point(_file(tmp_path / "a.mixar"), now=NOW, reason="t", cost_s=0.1, original_path="")
    jr.note_user_save("/p/scene.mixar", now=NOW + 5)
    data = journal.read_manifest(jr.dir)
    assert data["save_points"] == [] and data["project_saved"] == {"path": "/p/scene.mixar", "at": NOW + 5}
    assert not [f for f in os.listdir(jr.dir) if f.startswith("sp-")]


def test_opening_another_file_forgets_the_old_document(tmp_path):
    jr = journal.Journal(str(tmp_path / "recovery"), pid=42, now=NOW)
    jr.add_save_point(_file(tmp_path / "a.mixar"), now=NOW, reason="t", cost_s=0.1, original_path="")
    jr.add_snapshot("/c/1.mixar", now=NOW, original_path="")
    jr.reset_document("/p/other.mixar")
    data = journal.read_manifest(jr.dir)
    assert data["save_points"] == [] and data["snapshots"] == []
    assert data["document_path"] == "/p/other.mixar"


def test_the_lock_tells_a_live_session_from_a_dead_one(tmp_path):
    root = tmp_path / "recovery"
    jr = journal.Journal(str(root), pid=42, now=NOW)
    assert journal.is_locked(jr.dir)  # held by this process
    # Another process holds a lock, then dies: the OS releases it.
    other = root / "other"
    other.mkdir()
    script = textwrap.dedent(f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("journal", {journal.__file__!r})
        journal = importlib.util.module_from_spec(spec); spec.loader.exec_module(journal)
        assert journal.acquire_lock({str(other)!r}) is not None
    """)
    subprocess.run([sys.executable, "-c", script], check=True)
    assert not journal.is_locked(str(other))


def test_a_clean_exit_leaves_nothing_behind(tmp_path):
    root = tmp_path / "recovery"
    jr = journal.Journal(str(root), pid=42, now=NOW)
    jr.add_save_point(_file(tmp_path / "a.mixar"), now=NOW, reason="t", cost_s=0.1, original_path="")
    jr.close_clean()
    assert not os.path.exists(jr.dir)


def test_prune_keeps_live_and_recent_sessions(tmp_path):
    root = tmp_path / "recovery"
    old = _session(tmp_path, "old", started=NOW - journal.MAX_AGE_S - 10)
    dismissed = _session(tmp_path, "dismissed", started=NOW - 3600, resolved="dismissed",
                         resolved_at=NOW - journal.DISMISSED_KEEP_S - 10)
    recent = _session(tmp_path, "recent", started=NOW - 3600)
    live = _session(tmp_path, "live", started=NOW - journal.MAX_AGE_S - 10)
    removed = journal.prune(str(root), NOW, alive=lambda d: d == live["dir"])
    assert sorted(removed) == sorted([old["dir"], dismissed["dir"]])
    assert os.path.isdir(recent["dir"]) and os.path.isdir(live["dir"])


# =============================================================================
# Decision
# =============================================================================

def test_the_newest_crashed_session_is_offered_with_its_newest_point(tmp_path):
    a = _session(tmp_path, "a", save_points=[])
    a["save_points"] = [_point(tmp_path, "a", 1, NOW - 500), _point(tmp_path, "a", 2, NOW - 400)]
    b = _session(tmp_path, "b", pid=200)
    b["save_points"] = [_point(tmp_path, "b", 1, NOW - 60, original_path="/p/cs-go.mixar",
                               agent_scenes=[{"scene": "Scene", "session_id": "sid"}])]
    offer = decision.find_offer([a, b], now=NOW)
    assert offer["session"] == "b"
    assert offer["target"]["kind"] == "save_point" and offer["target"]["at"] == NOW - 60
    assert offer["name"] == "cs-go"
    assert offer["target"]["agent_scenes"] == [{"scene": "Scene", "session_id": "sid"}]
    assert [o["session"] for o in offer["older"]] == ["a"]
    assert offer["loop"] is False


def test_live_clean_and_resolved_sessions_are_never_offered(tmp_path):
    live = _session(tmp_path, "live", alive=True)
    live["save_points"] = [_point(tmp_path, "live", 1, NOW - 10)]
    clean = _session(tmp_path, "clean", clean_exit=True)
    clean["save_points"] = [_point(tmp_path, "clean", 1, NOW - 10)]
    done = _session(tmp_path, "done", resolved="restored")
    done["save_points"] = [_point(tmp_path, "done", 1, NOW - 10)]
    assert decision.find_offer([live, clean, done], now=NOW) is None


def test_untitled_work_is_offered_untitled(tmp_path):
    s = _session(tmp_path, "s")
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 30, original_path="")]
    offer = decision.find_offer([s], now=NOW)
    assert offer["target"]["original_path"] == "" and offer["name"] == ""


def test_a_project_saved_after_the_last_save_point_is_reopened_instead(tmp_path):
    project = _file(tmp_path / "proj" / "scene.mixar", mtime=NOW - 20)
    s = _session(tmp_path, "s", project_saved={"path": project, "at": NOW - 20})
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 100)]
    offer = decision.find_offer([s], now=NOW)
    assert offer["target"]["kind"] == "project" and offer["target"]["path"] == project


def test_a_project_changed_on_disk_since_the_save_is_not_trusted(tmp_path):
    # Saved at NOW-20 but the file on disk is older (replaced by a sync tool):
    # the save point is the state the user had.
    project = _file(tmp_path / "proj" / "scene.mixar", mtime=NOW - 500)
    s = _session(tmp_path, "s", project_saved={"path": project, "at": NOW - 20})
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 100)]
    assert decision.find_offer([s], now=NOW)["target"]["kind"] == "save_point"


def test_the_native_autosave_of_the_session_counts_when_newer(tmp_path):
    s = _session(tmp_path, "s", pid=321, document_path="/p/x.mixar")
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 300)]
    auto = _file(tmp_path / "T" / "x_321_autosave.mixar", mtime=NOW - 30)
    autos = decision.native_autosaves(str(tmp_path / "T"))
    offer = decision.find_offer([s], autosaves=autos, now=NOW)
    assert offer["target"]["kind"] == "autosave" and offer["target"]["path"] == auto
    assert offer["target"]["original_path"] == "/p/x.mixar"
    assert [c["kind"] for c in offer["fallbacks"]] == ["save_point"]


def test_missing_files_are_skipped(tmp_path):
    s = _session(tmp_path, "s")
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 300),
                        {"file": str(tmp_path / "gone.mixar"), "seq": 2, "at": NOW - 10}]
    assert decision.find_offer([s], now=NOW)["target"]["at"] == NOW - 300


def test_turn_checkpoints_and_inherited_points_are_the_last_fallbacks(tmp_path):
    snap = _file(tmp_path / "ckpt" / "abc.mixar")
    inherited = _file(tmp_path / "recovery" / "older" / "sp-9.mixar")
    s = _session(tmp_path, "s", snapshots=[{"file": snap, "at": NOW - 900, "original_path": ""}],
                 inherited_points=[{"path": inherited, "at": NOW - 600, "original_path": "/p/a.mixar"}])
    offer = decision.find_offer([s], now=NOW)
    assert offer["target"]["kind"] == "inherited"
    assert [c["kind"] for c in offer["fallbacks"]] == ["snapshot"]


# -- crash-loop guard ---------------------------------------------------------

def test_a_restore_that_crashed_is_never_offered_again(tmp_path):
    s1 = _session(tmp_path, "s1")
    p1 = _point(tmp_path, "s1", 1, NOW - 600)
    p2 = _point(tmp_path, "s1", 2, NOW - 300)
    s1["save_points"] = [p1, p2]
    # Launch 2 started restoring p2 and died before confirming it.
    s2 = _session(tmp_path, "s2", pid=200, started=NOW - 100,
                  restore_attempt={"point": p2["file"], "from_session": "s1", "at": NOW - 99,
                                   "confirmed": False})
    offer = decision.find_offer([s1, s2], now=NOW)
    assert offer["session"] == "s1"
    assert offer["target"]["path"] == p1["file"]
    assert offer["loop"] is True and offer["failed_points"] == [p2["file"]]
    assert offer["debris"] == [s2["dir"]]  # the dead restorer is resolved with it


def test_a_confirmed_restore_is_not_a_failure(tmp_path):
    s1 = _session(tmp_path, "s1")
    p2 = _point(tmp_path, "s1", 2, NOW - 300)
    s1["save_points"] = [p2]
    s2 = _session(tmp_path, "s2", pid=200, restore_attempt={"point": p2["file"], "confirmed": True})
    offer = decision.find_offer([s1, s2], now=NOW)
    assert offer["target"]["path"] == p2["file"] and offer["loop"] is False


def test_a_live_restorer_is_not_judged(tmp_path):
    s1 = _session(tmp_path, "s1")
    p2 = _point(tmp_path, "s1", 2, NOW - 300)
    s1["save_points"] = [p2]
    s2 = _session(tmp_path, "s2", pid=200, alive=True,
                  restore_attempt={"point": p2["file"], "confirmed": False})
    assert decision.find_offer([s1, s2], now=NOW)["target"]["path"] == p2["file"]


def test_failed_points_persist_after_the_dead_launch_is_gone(tmp_path):
    s1 = _session(tmp_path, "s1")
    p1 = _point(tmp_path, "s1", 1, NOW - 600)
    p2 = _point(tmp_path, "s1", 2, NOW - 300)
    s1["save_points"] = [p1, p2]
    s1["failed_points"] = [p2["file"]]
    offer = decision.find_offer([s1], now=NOW)
    assert offer["target"]["path"] == p1["file"] and offer["loop"] is True


def test_when_every_point_crashed_nothing_is_offered(tmp_path):
    s1 = _session(tmp_path, "s1")
    p1 = _point(tmp_path, "s1", 1, NOW - 600)
    s1["save_points"] = [p1]
    s1["failed_points"] = [p1["file"]]
    offer = decision.find_offer([s1], now=NOW)
    assert offer.get("target") is None and offer["debris"] == [s1["dir"]]


# -- legacy native autosaves (no journal) -------------------------------------

def test_a_legacy_autosave_of_a_dead_process_is_offered(tmp_path):
    temp = tmp_path / "T"
    _file(temp / "quit.blend", mtime=NOW - 3600)
    crashed = _file(temp / "cs-go-3_64632_autosave.mixar", mtime=NOW - 60)
    _file(temp / "older_62209_autosave.mixar", mtime=NOW - 7200)  # before the clean quit
    _file(temp / "running_777_autosave.mixar", mtime=NOW - 30)
    offer = decision.find_offer([], autosaves=decision.native_autosaves(str(temp)),
                                quit_mtime=os.path.getmtime(temp / "quit.blend"), now=NOW,
                                pid_alive=lambda pid: pid == 777)
    assert offer["legacy"] and offer["target"]["path"] == crashed and offer["name"] == "cs-go-3"


def test_a_journaled_session_claims_its_own_autosave(tmp_path):
    temp = tmp_path / "T"
    _file(temp / "64632_autosave.mixar", mtime=NOW - 60)
    s = _session(tmp_path, "s", pid=64632, resolved="dismissed")
    offer = decision.find_offer([s], autosaves=decision.native_autosaves(str(temp)), now=NOW)
    assert offer is None


# =============================================================================
# Scheduler
# =============================================================================

def _sched(**policy):
    s = SavePointScheduler(policy=Policy(**policy))
    s.reset(0.0)
    return s


def test_a_script_burst_saves_once_after_it_settles():
    s = _sched(settle_s=2.0, min_gap_s=0.0)
    for t in (100.0, 100.5, 101.0, 101.5):
        s.request("agent_script", t)
        assert s.due(t + 0.1, busy=False, dirty=True) == (False, [])
    assert s.due(103.6, busy=False, dirty=True) == (True, ["agent_script"])
    s.record_save(103.6, 0.2, True)
    assert s.due(104.0, busy=False, dirty=True) == (False, [])


def test_a_continuous_burst_still_saves_every_max_defer():
    s = _sched(settle_s=2.0, max_defer_s=60.0, min_gap_s=0.0)
    t = 100.0
    while t < 159.0:
        s.request("agent_script", t)
        assert not s.due(t, busy=False, dirty=True)[0]
        t += 1.0
    s.request("agent_script", 160.0)
    assert s.due(160.0, busy=False, dirty=True)[0]


def test_busy_defers_and_keeps_the_request():
    s = _sched(min_gap_s=0.0)
    s.request("generation_import", 100.0)
    assert s.due(110.0, busy=True, dirty=True) == (False, [])
    assert s.due(111.0, busy=False, dirty=True) == (True, ["generation_import"])


def test_spacing_grows_with_what_a_save_costs():
    s = _sched(min_gap_s=15.0, cost_factor=20.0, settle_s=0.0)
    s.record_save(100.0, 3.0, True)  # a heavy scene: 3 s per save
    assert s.gap_s() == 60.0
    s.request("turn_end", 120.0)
    assert not s.due(150.0, busy=False, dirty=True)[0]
    assert s.due(160.0, busy=False, dirty=True)[0]


def test_the_timer_saves_only_a_changed_document():
    s = _sched(timer_s=120.0)
    assert s.due(200.0, busy=False, dirty=False) == (False, [])
    s.note_change()
    assert s.due(200.0, busy=False, dirty=False) == (True, ["timer"])
    s.record_save(200.0, 0.1, True)
    assert s.due(400.0, busy=False, dirty=False) == (False, [])  # nothing changed since
    assert s.due(400.0, busy=False, dirty=True) == (True, ["timer"])


def test_a_failed_write_retries_later():
    s = _sched(min_gap_s=0.0, settle_s=0.0, retry_s=30.0)
    s.request("turn_end", 100.0)
    s.record_save(100.0, 0.1, False)
    assert not s.due(110.0, busy=False, dirty=True)[0]
    assert s.due(131.0, busy=False, dirty=True) == (True, ["turn_end"])


def test_a_new_document_waits_a_full_interval():
    s = _sched(timer_s=120.0)
    s.reset(1000.0)
    assert not s.due(1100.0, busy=False, dirty=True)[0]
    assert s.due(1121.0, busy=False, dirty=True)[0]


# =============================================================================
# Generations
# =============================================================================

class _State(str, Enum):
    RUNNING_POLL = "RUNNING_POLL"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"


@dataclass
class AsyncGLBJob:
    feature_key: str = ""
    label: str = ""
    scene_name: str = ""
    service: str = ""
    model: str = ""
    backend_job_id: str = ""
    job_type: str = ""
    agent_ref: dict = field(default_factory=dict)
    state: _State = _State.PENDING
    payload: dict = field(default_factory=dict)


@dataclass
class MatGenJob:
    label: str = ""
    backend_job_id: str = ""
    state: _State = _State.PENDING


def test_only_submitted_unfinished_jobs_are_recorded():
    running = AsyncGLBJob(feature_key="model_gen", label="Chair", scene_name="Scene 2",
                          service="model_3d", model="tripo", backend_job_id="j1", job_type="model_3d",
                          agent_ref={"session_id": "s", "nested": {"x": 1}}, state=_State.RUNNING_POLL,
                          payload={"image": "b64…"})
    unsubmitted = AsyncGLBJob(label="later", state=_State.PENDING)
    done = AsyncGLBJob(label="done", backend_job_id="j2", state=_State.SUCCESS)
    bespoke = MatGenJob(label="Brick", backend_job_id="j3", state=_State.RUNNING_POLL)
    records = jobs.describe([running, unsubmitted, done, bespoke])
    assert [r["backend_job_id"] for r in records] == ["j1", "j3"]
    assert records[0]["agent_ref"] == {"session_id": "s"}  # nested values dropped
    assert "payload" not in records[0] and "state" not in records[0]
    adoptable, other = jobs.split(records)
    assert [r["label"] for r in adoptable] == ["Chair"] and [r["label"] for r in other] == ["Brick"]
    job = jobs.rebuild(adoptable[0], {"AsyncGLBJob": AsyncGLBJob})
    assert (job.label, job.scene_name, job.backend_job_id, job.feature_key) == \
        ("Chair", "Scene 2", "j1", "model_gen")
    assert jobs.rebuild(other[0], {"AsyncGLBJob": AsyncGLBJob}) is None


# =============================================================================
# Runtime helpers
# =============================================================================

def test_runtime_names_the_native_autosave_like_wm_files(monkeypatch):
    from mixar.modules.session_recovery import runtime

    monkeypatch.setattr(runtime.bpy.app, "tempdir", "/T/blender_abc/", raising=False)
    monkeypatch.setattr(runtime.bpy.data, "filepath", "/p/cs-go-3.mixar", raising=False)
    monkeypatch.setattr(runtime.os, "getpid", lambda: 4242)
    assert runtime.native_autosave_path() == os.path.join("/T", "cs-go-3_4242_autosave.mixar")
    monkeypatch.setattr(runtime.bpy.data, "filepath", "", raising=False)
    assert runtime.native_autosave_path() == os.path.join("/T", "4242_autosave.mixar")


@pytest.mark.parametrize("idname,expected", [
    ("mixar.agent_viewport_block", "MIXAR_OT_agent_viewport_block"),
    ("TRANSFORM_OT_translate", "TRANSFORM_OT_translate"),
])
def test_modal_operator_names_match_the_native_passive_list(idname, expected):
    from mixar.modules.session_recovery import runtime

    class Op:
        bl_idname = idname
    assert runtime._op_idname(Op()) == expected


def test_the_passive_list_matches_the_native_autosave():
    import re
    src = open("src/source/blender/windowmanager/intern/wm_files.cc").read()
    native = set(re.findall(r'"([A-Z_]+_OT_\w+)"', re.search(
        r"passive_idnames\[\] = \{(.*?)\};", src, re.S).group(1)))
    from mixar.modules.session_recovery import runtime
    assert native == set(runtime.PASSIVE_MODALS)


# =============================================================================
# Runtime flows (bpy mocked)
# =============================================================================

@pytest.fixture
def rt(tmp_path, monkeypatch):
    from mixar.modules.session_recovery import runtime
    from mixar.modules.session_recovery.scheduler import SavePointScheduler

    jr = journal.Journal(str(tmp_path / "recovery"), pid=4242, now=NOW)
    sched = SavePointScheduler()
    sched.reset(0.0)
    monkeypatch.setitem(runtime._state, "journal", jr)
    monkeypatch.setitem(runtime._state, "scheduler", sched)
    monkeypatch.setitem(runtime._state, "decided", False)
    monkeypatch.setattr(runtime, "_main_window", lambda: None)
    monkeypatch.setattr(runtime, "native_autosave_path", lambda: str(tmp_path / "T" / "4242_autosave.mixar"))
    monkeypatch.setattr(runtime, "_tab_scenes", lambda: [])
    monkeypatch.setattr(runtime, "agent_scenes", lambda: [{"scene": "Scene", "session_id": "sid"}])
    monkeypatch.setattr(runtime, "_job_records", lambda: [])
    monkeypatch.setattr(runtime.bpy.data, "filepath", "", raising=False)
    monkeypatch.setattr(runtime.bpy.app.timers, "register",
                        lambda fn, first_interval=0, persistent=False: None, raising=False)
    return runtime


def test_a_save_point_is_the_native_autosave_moved_into_the_journal(rt, tmp_path, monkeypatch):
    def save_auto_save():
        _file(tmp_path / "T" / "4242_autosave.mixar", data=b"blend")
        return {'FINISHED'}
    monkeypatch.setattr(rt.bpy.ops.wm, "save_auto_save", save_auto_save, raising=False)
    record = rt.write_save_point(["agent_script"])
    assert record["reason"] == "agent_script" and record["agent_scenes"][0]["session_id"] == "sid"
    assert os.path.isfile(record["file"]) and not os.path.exists(tmp_path / "T" / "4242_autosave.mixar")
    assert rt._state["scheduler"].last_cost_s == pytest.approx(record["cost_s"], abs=1e-3)


def test_a_failed_write_files_nothing(rt, monkeypatch):
    monkeypatch.setattr(rt.bpy.ops.wm, "save_auto_save", lambda: {'CANCELLED'}, raising=False)
    assert rt.write_save_point(["timer"]) is None
    assert rt._state["journal"].data["save_points"] == []
    assert rt._state["scheduler"].last_failed_at > 0


def test_the_restore_attempt_is_on_disk_before_the_read(rt, tmp_path, monkeypatch):
    point = _file(tmp_path / "recovery" / "old" / "sp-1.mixar")
    old = _session(tmp_path, "old2")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "old2", "dir": old["dir"], "legacy": False, "failed_points": [],
        "older": [], "debris": [],
        "target": {"kind": "save_point", "path": point, "at": NOW - 60, "original_path": "",
                   "agent_scenes": [], "jobs": []}})
    seen = {}

    def recover_auto_save(filepath):
        seen["manifest"] = journal.read_manifest(rt._state["journal"].dir)
        seen["path"] = filepath
        return {'FINISHED'}
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save", recover_auto_save, raising=False)
    import mixar.modules.space_mixie_chat.core.checkpoint_timeline as ct
    monkeypatch.setattr(ct, "_retitle", lambda path: seen.setdefault("retitle", path))
    monkeypatch.setattr(ct, "_keep_modified", lambda path: (lambda: None))
    assert rt.restore_deferred()
    rt._restore_now()
    attempt = seen["manifest"]["restore_attempt"]
    assert attempt == {"point": point, "from_session": "old2", "at": attempt["at"], "confirmed": False}
    assert seen["path"] == point and seen["retitle"] == ""  # untitled stays untitled
    inherited = rt._state["journal"].data["inherited_points"]
    assert inherited[0]["path"] == point and inherited[0]["source_dir"] == old["dir"]
    rt._confirm_restore()
    assert rt._state["journal"].data["restore_attempt"]["confirmed"] is True
    assert journal.read_manifest(old["dir"])["resolved"] == "restored"


def test_a_read_that_fails_keeps_the_work_for_next_launch(rt, tmp_path, monkeypatch):
    point = _file(tmp_path / "recovery" / "old" / "sp-1.mixar")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "old", "dir": "", "legacy": False, "failed_points": [], "older": [], "debris": [],
        "target": {"kind": "save_point", "path": point, "at": NOW, "original_path": ""}})
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save", lambda filepath: {'CANCELLED'}, raising=False)
    monkeypatch.setattr(rt, "_report", lambda text: None)
    assert rt.restore_deferred()
    rt._restore_now()
    assert rt._state["journal"].data.get("restore_attempt") is None
    assert rt._state["decided"] is False and rt.current_offer() is not None


def test_start_fresh_resolves_the_session_and_retires_legacy_files(rt, tmp_path, monkeypatch):
    crashed = _session(tmp_path, "crashed")
    legacy = _file(tmp_path / "T" / "x_9_autosave.mixar")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "crashed", "dir": crashed["dir"], "legacy": False, "failed_points": [],
        "debris": [], "target": {"kind": "save_point", "path": "p", "at": NOW},
        "older": [{"legacy": True, "dir": "", "target": {"path": legacy}}]})
    rt.discard_offer()
    assert journal.read_manifest(crashed["dir"])["resolved"] == "dismissed"
    assert not os.path.exists(legacy) and os.path.exists(legacy + ".dismissed")
    assert rt.current_offer() is None


def test_an_autosave_target_keeps_what_the_newest_save_point_knew(tmp_path):
    # QA 2026-10-30: the machine slept after the last save point, the native
    # autosave on wake won, and the Continue notice was lost with its metadata.
    s = _session(tmp_path, "s", pid=321)
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 300, scenes=["A", "B"],
                               agent_scenes=[{"scene": "A", "session_id": "sid"}],
                               jobs=[{"cls": "AsyncGLBJob", "backend_job_id": "j"}])]
    _file(tmp_path / "T" / "321_autosave.mixar", mtime=NOW - 30)
    offer = decision.find_offer([s], autosaves=decision.native_autosaves(str(tmp_path / "T")), now=NOW)
    target = offer["target"]
    assert target["kind"] == "autosave"
    assert target["agent_scenes"] == [{"scene": "A", "session_id": "sid"}]
    assert target["scenes"] == ["A", "B"] and target["jobs"][0]["backend_job_id"] == "j"


def test_a_clock_that_moved_backwards_does_not_stop_saving():
    s = _sched(timer_s=120.0)
    s.record_save(10_000.0, 0.1, True)
    s.note_change()
    assert s.due(5_000.0, busy=False, dirty=True) == (True, ["timer"])


def test_save_points_from_before_a_restore_are_dropped(rt, tmp_path, monkeypatch):
    jr = rt._state["journal"]
    jr.add_save_point(_file(tmp_path / "startup.mixar"), now=NOW, reason="timer", cost_s=0.01,
                      original_path="")
    point = _file(tmp_path / "recovery" / "old" / "sp-1.mixar")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "old", "dir": "", "legacy": False, "failed_points": [], "older": [], "debris": [],
        "target": {"kind": "save_point", "path": point, "at": NOW - 60, "original_path": "",
                   "agent_scenes": [], "jobs": []}})
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save", lambda filepath: {'FINISHED'}, raising=False)
    import mixar.modules.space_mixie_chat.core.checkpoint_timeline as ct
    monkeypatch.setattr(ct, "_retitle", lambda path: None)
    monkeypatch.setattr(ct, "_keep_modified", lambda path: (lambda: None))
    assert rt.restore_deferred()
    rt._restore_now()
    assert jr.data["save_points"] == []
    assert [p["path"] for p in jr.data["inherited_points"]] == [point]


def test_restored_tabs_are_settled_idle_when_connected(rt, monkeypatch):
    # QA 2026-10-31: a tab saved mid-turn came back BUSY and Continue was refused.
    calls = []

    class Session:
        def set_run(self, scene, run_id, open_):
            calls.append(("run", scene, open_))

        def set_connected(self, scene):
            calls.append(("idle", scene))

        def set_disconnected(self, scene):
            calls.append(("offline", scene))

    class Client:
        is_connected = True

    import mixar.modules.space_mixie_chat.core.jsonrpc_client as jc
    monkeypatch.setattr(jc, "get_jsonrpc_client", lambda: Client())
    monkeypatch.setattr(rt, "_session_manager", lambda: Session())
    monkeypatch.setattr(rt, "_tab_scenes", lambda: ["A", "B"])
    rt._settle_restored_scenes()
    assert calls == [("run", "A", False), ("idle", "A"), ("run", "B", False), ("idle", "B")]
    Client.is_connected = False
    calls.clear()
    rt._settle_restored_scenes()
    assert ("offline", "A") in calls and ("idle", "A") not in calls
