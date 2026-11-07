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
    native = set(re.findall(r'"([A-Z0-9_]+_OT_\w+)"', re.search(
        r"passive_idnames\[\] = \{(.*?)\};", src, re.S).group(1)))
    from mixar.modules.session_recovery import runtime
    assert native == set(runtime.PASSIVE_MODALS)


# Every Mixar modal operator is classified: passive ones never defer a save,
# editing ones (an edit or a stroke in flight) do. A new modal fails here
# until someone decides which it is.
EDITING_MODALS = {
    # Drags and tools with an edit in flight.
    "MIXAR_OT_director_drag_keys", "MIXAR_OT_director_pick_track_target",
    "MIXAR_OT_director_drag_frame", "MIXAR_OT_director_drag_strip", "MIXAR_OT_director_scrub",
    "MIXAR_OT_director_walk", "MIXAR_OT_director_place_camera", "MIXAR_OT_director_nudge_camera",
    "MIXAR_OT_bubble_header_drag", "MIXAR_OT_scribble_mark_draw",
    "MIXIE_OT_moodboard_add_textbox", "MIXIE_OT_moodboard_magic_select_tool",
    "MIXIE_OT_moodboard_grab", "MIXIE_OT_moodboard_rotate", "MIXIE_OT_moodboard_scale",
    "MIXIE_OT_moodboard_annotation_stroke", "MIXIE_OT_moodboard_annotation_erase",
    "MIXIE_OT_moodboard_edit_textbox", "MIXIE_OT_moodboard_crop_tool",
    "MIXIE_OT_moodboard_box_mask_tool", "MIXIE_OT_moodboard_lasso_tool",
    "MIXIE_OT_moodboard_graph_select", "MIXIE_OT_moodboard_frame_select",
    "MIXIE_OT_moodboard_box_select", "MIXIE_OT_moodboard_select_image",
    "MIXIE_CHAT_OT_select_text", "VIEW3D_OT_scenes_drawer_edge", "VIEW3D_OT_scenes_drawer_click",
    "VIEW3D_OT_moodboard_drawer_grip",
}


def _mixar_modal_idnames():
    import ast
    import re
    from pathlib import Path
    found = set()
    for path in Path("src/scripts/mixar/modules").rglob("*.py"):
        if "/tests/" in str(path) or "/testing/" in str(path):
            continue
        tree = ast.parse(path.read_text(errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(n, ast.FunctionDef) and n.name == "modal" for n in node.body):
                continue
            for n in node.body:
                if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "bl_idname"
                        and isinstance(n.value, ast.Constant)):
                    prefix, name = n.value.value.split(".", 1)
                    found.add(f"{prefix.upper()}_OT_{name}")
    found.add("MIXAR_OT_onboarding_tour")  # bl_idname = config.OP_TOUR
    for path in Path("src/source/blender/editors").rglob("*.cc"):
        text = path.read_text(errors="ignore")
        first = text.split("\n", 1)[0]
        if "Adeveda" not in first and "Mixar" not in first:
            continue  # an upstream file carried in the overlay: stock modals
        for body in re.findall(r"\n(?:static )?void \w+\(wmOperatorType \*ot\)\n\{(.*?)\n\}", text, re.S):
            if "ot->modal = " in body:
                found |= set(re.findall(r'ot->idname = "(\w+)"', body))
    return found


def test_every_mixar_modal_operator_is_classified():
    from mixar.modules.session_recovery import runtime
    found = _mixar_modal_idnames()
    assert "MIXAR_OT_credits_banner" in found and "MIXAR_OT_director_walk" in found
    assert not set(runtime.PASSIVE_MODALS) & EDITING_MODALS
    assert found - set(runtime.PASSIVE_MODALS) - EDITING_MODALS == set()


@pytest.mark.parametrize("open_modals,busy", [
    (["MIXAR_OT_credits_banner"], False),            # the banner of #1787
    (["MIXAR_OT_onboarding_tour", "MIXAR_OT_agent_viewport_block"], False),
    (["MIXAR_OT_credits_banner", "TRANSFORM_OT_translate"], True),   # a real drag
])
def test_popups_never_defer_a_save_point(monkeypatch, open_modals, busy):
    from types import SimpleNamespace
    from mixar.modules.session_recovery import runtime

    window = SimpleNamespace(modal_operators=[SimpleNamespace(bl_idname=i) for i in open_modals])
    monkeypatch.setitem(runtime._state, "restoring", False)
    monkeypatch.setattr(runtime.bpy, "context", SimpleNamespace(
        window_manager=SimpleNamespace(windows=[window])), raising=False)
    monkeypatch.setattr(runtime.bpy.app, "is_job_running", lambda kind: False, raising=False)
    import mixar.modules.space_mixie_chat.core.turn_checkpoints as tc
    import mixar.modules.space_mixie_chat.core.main_thread_executor as mte
    monkeypatch.setattr(tc, "is_restoring", lambda: False)
    monkeypatch.setattr(mte, "has_pending_requests", lambda: False)
    monkeypatch.setattr(mte, "get_inflight_script", lambda: None)
    assert runtime._busy() is busy


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


# -- the crashed session a restore came from ----------------------------------

def _restored_journal(tmp_path, *, confirmed):
    """Launch B restored launch A's ``sp-2``; A's directory is the fallback."""
    root = str(tmp_path / "recovery")
    a = _session(tmp_path, "a")
    a["save_points"] = [_point(tmp_path, "a", 1, NOW - 900), _point(tmp_path, "a", 2, NOW - 600)]
    journal.write_manifest(a["dir"], {k: v for k, v in a.items() if k not in ("dir", "alive")})
    jr = journal.Journal(root, pid=4242, now=NOW - 60, session="b")
    jr.set_fields(restore_attempt={"point": a["save_points"][1]["file"], "from_session": "a",
                                   "at": NOW - 60, "confirmed": confirmed})
    jr.set_inherited([{"kind": "save_point", "path": a["save_points"][1]["file"], "at": NOW - 600,
                       "original_path": "", "source_dir": a["dir"]}])
    return a, jr


def test_an_unconfirmed_restore_keeps_the_crashed_session_it_came_from(tmp_path):
    # A save point lands 15 s after the restore, confirmation only at 20 s: a
    # crash between them must still find A's older points and the loop.
    a, jr = _restored_journal(tmp_path, confirmed=False)
    jr.add_save_point(_file(tmp_path / "T" / "b.mixar"), now=NOW - 45, reason="timer",
                      cost_s=0.1, original_path="")
    assert os.path.isdir(a["dir"]) and jr.data["inherited_points"]
    sessions = journal.list_sessions(str(tmp_path / "recovery"), alive=lambda d: False)
    offer = decision.find_offer(sessions, now=NOW)
    assert offer["session"] == "b" and offer["loop"] is True
    assert offer["failed_points"] == [a["save_points"][1]["file"]]
    # A's older point is still on offer, never the one whose restore crashed.
    older = [o["target"]["path"] for o in offer["older"]]
    assert older == [a["save_points"][0]["file"]]


def test_a_confirmed_restore_drops_its_source_at_the_next_save_point(tmp_path):
    a, jr = _restored_journal(tmp_path, confirmed=True)
    jr.add_save_point(_file(tmp_path / "T" / "b.mixar"), now=NOW - 45, reason="timer",
                      cost_s=0.1, original_path="")
    assert not os.path.exists(a["dir"]) and jr.data["inherited_points"] == []


def test_confirmation_drops_the_source_only_once_a_save_point_covers_it(rt, tmp_path, monkeypatch):
    a, _ = _restored_journal(tmp_path, confirmed=False)
    jr = rt._state["journal"]
    jr.set_fields(restore_attempt={"point": a["save_points"][1]["file"], "confirmed": False})
    jr.set_inherited([{"path": a["save_points"][1]["file"], "at": NOW - 600, "source_dir": a["dir"]}])
    monkeypatch.setitem(rt._state, "offer", {"session": "a", "dir": a["dir"], "older": [], "debris": []})
    rt._confirm_restore()
    assert jr.data["restore_attempt"]["confirmed"] is True
    assert os.path.isdir(a["dir"])  # nothing of ours covers the document yet
    jr.add_save_point(_file(tmp_path / "T" / "c.mixar"), now=NOW, reason="timer",
                      cost_s=0.1, original_path="")
    assert not os.path.exists(a["dir"])


def test_confirming_after_a_save_point_drops_the_source_at_once(rt, tmp_path, monkeypatch):
    a, _ = _restored_journal(tmp_path, confirmed=False)
    jr = rt._state["journal"]
    jr.set_fields(restore_attempt={"point": a["save_points"][1]["file"], "confirmed": False})
    jr.set_inherited([{"path": a["save_points"][1]["file"], "at": NOW - 600, "source_dir": a["dir"]}])
    jr.add_save_point(_file(tmp_path / "T" / "d.mixar"), now=NOW, reason="timer",
                      cost_s=0.1, original_path="")
    assert os.path.isdir(a["dir"])
    monkeypatch.setitem(rt._state, "offer", {"session": "a", "dir": a["dir"], "older": [], "debris": []})
    rt._confirm_restore()
    assert not os.path.exists(a["dir"]) and jr.data["inherited_points"] == []


# -- generations that landed before the crash -----------------------------------

def test_a_job_that_landed_before_a_candidate_was_written_is_not_adopted_again(tmp_path):
    s = _session(tmp_path, "s", pid=321, landed_jobs=[{"id": "done", "at": NOW - 200}])
    s["save_points"] = [_point(tmp_path, "s", 1, NOW - 300, jobs=[
        {"cls": "AsyncGLBJob", "backend_job_id": "done"},
        {"cls": "AsyncGLBJob", "backend_job_id": "running"}])]
    _file(tmp_path / "T" / "321_autosave.mixar", mtime=NOW - 30)
    offer = decision.find_offer([s], autosaves=decision.native_autosaves(str(tmp_path / "T")), now=NOW)
    # The autosave was written after "done" was imported: it holds the result.
    assert offer["target"]["kind"] == "autosave"
    assert [j["backend_job_id"] for j in offer["target"]["jobs"]] == ["running"]
    # The save point predates the import: restoring it must import "done" again.
    fallback = offer["fallbacks"][0]
    assert fallback["kind"] == "save_point"
    assert [j["backend_job_id"] for j in fallback["jobs"]] == ["done", "running"]


def test_landed_jobs_are_journaled_bounded_and_on_disk(tmp_path):
    jr = journal.Journal(str(tmp_path / "recovery"), pid=42, now=NOW)
    for i in range(journal.KEEP_LANDED_JOBS + 5):
        jr.note_job_landed(f"j{i}", now=NOW + i)
    jr.note_job_landed("j10", now=NOW + 999)  # landing twice keeps the latest
    landed = journal.read_manifest(jr.dir)["landed_jobs"]
    assert len(landed) == journal.KEEP_LANDED_JOBS
    assert landed[-1] == {"id": "j10", "at": NOW + 999}
    assert [e["id"] for e in landed].count("j10") == 1


def test_runtime_notes_a_landed_job_and_never_raises(rt, monkeypatch):
    rt.note_job_landed("abc")
    assert rt._state["journal"].data["landed_jobs"][-1]["id"] == "abc"
    rt.note_job_landed("")
    assert len(rt._state["journal"].data["landed_jobs"]) == 1
    monkeypatch.setitem(rt._state, "journal", None)
    rt.note_job_landed("abc")


# =============================================================================
# Every way a turn ends asks for a save point
# =============================================================================

def test_ending_one_sessions_turn_asks_for_a_save_point(monkeypatch):
    from mixar.modules.session_recovery import runtime
    from mixar.modules.space_mixie_chat.core import executor as executor_mod

    asked = []
    monkeypatch.setattr(runtime, "request_save_point", asked.append)
    ex = executor_mod.ScriptExecutor()
    ex._turns.clear()
    ex.end_agent_turn("sess-a")                     # never started (a refusal) still asks
    ex.begin_agent_turn("sess-b")
    ex.end_agent_turn("sess-b", checkpoint=False)
    assert asked == ["turn_end", "turn_end"]
    ex.end_agent_turn(None)                         # file load / shutdown: nothing to save
    assert asked == ["turn_end", "turn_end"]

    def boom(reason):
        raise RuntimeError("recovery off")
    monkeypatch.setattr(runtime, "request_save_point", boom)
    ex.begin_agent_turn("sess-c")
    ex.end_agent_turn("sess-c")                     # never breaks the turn's end
    assert "sess-c" not in ex._turns


@pytest.mark.parametrize("path,function", [
    ("queue_processor.py", "_handle_agent_complete_internal"),   # stream complete / turn_end
    ("queue_processor.py", "_handle_inband_error"),
    ("queue_processor.py", "_end_refused_turn"),
    ("queue_processor.py", "_handle_agent_error_internal"),      # stream error
    ("turn_events.py", "_replay_unavailable"),
])
def test_every_turn_ending_passes_through_end_agent_turn(path, function):
    import ast
    from pathlib import Path
    source = Path("src/scripts/mixar/modules/space_mixie_chat/core", path).read_text()
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == function)
    body = ast.get_source_segment(source, node)
    assert "end_agent_turn(getattr(scene, \"mixie_session_id\", \"\") or \"\"" in body
    # One convergence point: no turn ending asks for a save point itself.
    assert "request_save_point" not in source


# =============================================================================
# Unsaved Work: every crashed session that can still be opened
# =============================================================================

def _crashed(tmp_path, name, at, **fields):
    """A dead session on disk with one save point (manifest included)."""
    extra = fields.pop("point", {})
    session = _session(tmp_path, name, **fields)
    session["save_points"] = [_point(tmp_path, name, 1, at, scenes=["Scene", "Scene.001"], **extra)]
    journal.write_manifest(session["dir"], {k: v for k, v in session.items()
                                            if k not in ("dir", "alive")})
    return session


def test_unsaved_work_lists_dismissed_and_superseded_but_never_live_clean_or_restored(tmp_path):
    sessions = [
        _crashed(tmp_path, "fresh", NOW - 100, point={"original_path": "/p/castle.mixar"}),
        _crashed(tmp_path, "dismissed", NOW - 200, resolved="dismissed", resolved_at=NOW - 50),
        _crashed(tmp_path, "superseded", NOW - 300, resolved="superseded", resolved_at=NOW - 50),
        dict(_crashed(tmp_path, "live", NOW - 10), alive=True),       # another Mixar holds it
        _crashed(tmp_path, "clean", NOW - 10, clean_exit=True),
        _crashed(tmp_path, "restored", NOW - 10, resolved="restored"),
        _crashed(tmp_path, "mine", NOW - 10),
        _crashed(tmp_path, "source", NOW - 10),
    ]
    listed = decision.unsaved_sessions(sessions, own_session="mine", skip={"source"})
    assert [e["session"] for e in listed] == ["fresh", "dismissed", "superseded"]
    assert listed[0]["name"] == "castle" and listed[1]["name"] == ""
    assert listed[1]["resolved"] == "dismissed" and listed[0]["older"] == []
    # The same candidate rules as the startup offer: a point whose restore
    # crashed is never listed.
    loop = _crashed(tmp_path, "loop", NOW - 5)
    died = _session(tmp_path, "died", restore_attempt={
        "point": loop["save_points"][0]["file"], "confirmed": False})
    assert "loop" not in [e["session"] for e in decision.unsaved_sessions([loop, died])]


def test_start_fresh_only_stops_the_prompt_and_keeps_the_copy(rt, tmp_path, monkeypatch):
    crashed = _crashed(tmp_path, "crashed", NOW - 60)
    offer = decision.find_offer(journal.list_sessions(str(tmp_path / "recovery"), alive=lambda d: False),
                                now=NOW)
    monkeypatch.setitem(rt._state, "offer", offer)
    rt.discard_offer()
    assert rt.current_offer() is None
    assert os.path.isfile(crashed["save_points"][0]["file"])          # nothing deleted
    sessions = journal.list_sessions(str(tmp_path / "recovery"), alive=lambda d: False)
    assert [e["session"] for e in decision.unsaved_sessions(sessions)] == ["crashed"]


def test_an_unsaved_entry_restores_through_the_startup_flow(rt, tmp_path, monkeypatch):
    newest = _crashed(tmp_path, "newest", NOW - 60)
    older = _crashed(tmp_path, "older", NOW - 600, resolved="dismissed", resolved_at=NOW - 30)
    sessions = journal.list_sessions(str(tmp_path / "recovery"), alive=lambda d: False)
    sessions = [s for s in sessions if s["session"] in ("newest", "older")]
    monkeypatch.setitem(rt._state, "offer", decision.find_offer(sessions, now=NOW))
    entry = next(e for e in decision.unsaved_sessions(sessions) if e["session"] == "older")
    read = []
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save",
                        lambda filepath: read.append(filepath) or {'FINISHED'}, raising=False)
    monkeypatch.setattr(rt.bpy.app.timers, "is_registered", lambda fn: False, raising=False)
    import mixar.modules.space_mixie_chat.core.checkpoint_timeline as ct
    monkeypatch.setattr(ct, "_retitle", lambda path: None)
    monkeypatch.setattr(ct, "_keep_modified", lambda path: (lambda: None))
    assert rt.restore_entry(entry)
    assert rt.current_offer() is None             # the prompt is answered
    rt._restore_now()
    assert read == [older["save_points"][0]["file"]]
    rt._confirm_restore()
    assert journal.read_manifest(older["dir"])["resolved"] == "restored"
    # The startup offer it replaced is superseded, not offered again; its files stay.
    assert journal.read_manifest(newest["dir"])["resolved"] == "superseded"
    assert os.path.isfile(newest["save_points"][0]["file"])


def test_a_second_restore_waits_for_the_first(rt, monkeypatch):
    monkeypatch.setattr(rt.bpy.app.timers, "is_registered", lambda fn: fn is rt._restore_now, raising=False)
    assert rt.restore_entry({"session": "x", "target": {"kind": "save_point", "path": "p", "at": NOW}}) is False


def test_a_session_another_mixar_holds_is_never_found(rt, tmp_path, monkeypatch):
    from mixar.modules.session_recovery import prompt
    _crashed(tmp_path, "dead", NOW - 60)
    live = journal.Journal(str(tmp_path / "recovery"), pid=77, now=NOW)   # holds its lock
    jr = journal.Journal(str(tmp_path / "recovery"), pid=4242, now=NOW, session="own")
    live.add_save_point(_file(tmp_path / "l.mixar"), now=NOW, reason="t", cost_s=0.1, original_path="")
    monkeypatch.setitem(rt._state, "journal", jr)
    monkeypatch.setattr(rt, "recovery_root", lambda: str(tmp_path / "recovery"))
    monkeypatch.setattr(rt, "tempdir_base", lambda: str(tmp_path / "T"))
    assert [e["session"] for e in prompt.scan()] == ["dead"]
    assert prompt.find(live.session) is None and prompt.find("own") is None
    assert prompt.find("dead")["session"] == "dead"


def test_an_unsaved_entry_reads_name_age_and_tabs(monkeypatch):
    from mixar.modules.session_recovery import prompt
    entry = {"name": "", "target": {"at": NOW - 7200, "scenes": ["A", "B"]}}
    assert prompt.entry_text(entry, NOW) == "Untitled · 2 h ago · 2 tabs"
    entry = {"name": "castle", "target": {"at": NOW - 30, "scenes": ["A"]}}
    assert prompt.entry_text(entry, NOW) == "castle · just now · 1 tab"
    assert prompt.age_text(NOW - 3 * 86400, NOW) == "3 days ago"
    assert prompt.entry_text({"name": "x", "target": {"at": NOW - 600}}, NOW) == "x · 10 min ago"


def test_recent_projects_skip_missing_and_non_project_files(tmp_path):
    from mixar.modules.common.utils.recent_files import recent_project_paths
    work = tmp_path / "work"
    work.mkdir()
    files = [work / f"p{i}.mixar" for i in range(7)]
    for f in files:
        f.write_bytes(b"BLENDER")
    (work / "notes.txt").write_text("x")
    history = [files[0], work / "gone.mixar", work / "notes.txt", files[0], *files[1:]]
    (tmp_path / "recent-files.txt").write_text("\n".join(map(str, history)) + "\n")
    assert recent_project_paths(str(tmp_path), 5) == files[:5]
    assert recent_project_paths(str(tmp_path / "none"), 5) == []


def test_the_splash_lists_recent_and_unsaved_work_and_never_the_last_session():
    from pathlib import Path
    splash = Path("src/scripts/mixar/bootstrap/splash_menu.py").read_text()
    assert "recover_last_session" not in splash.split('"""', 2)[2]   # outside the docstring
    assert "recent_project_paths(" in splash and "display_file_selector = False" in splash
    draw = splash[splash.index("class WM_MT_splash"):]
    # The restore block stays first; the lists come after the mode picker.
    assert draw.index("draw_offer(") < draw.index('"mixar.set_ui_mode_ai"') < draw.index(
        "_draw_recent_and_unsaved(")
    # No journal read on an ordinary redraw: only a new opening re-reads.
    lists = splash[splash.index("def _refresh_lists"):splash.index("def _draw_recent_and_unsaved")]
    assert "if reopened:" in lists and "prompt.scan()" in lists


def test_file_recover_gets_unsaved_work_from_mixar_code():
    from pathlib import Path
    boot = Path("src/scripts/mixar/bootstrap/session_recovery_module.py").read_text()
    assert "recover_menu.append(_draw_recover_entry)" in boot
    assert "recover_menu.remove(_draw_recover_entry)" in boot
    stock = Path("src/scripts/startup/bl_ui/space_topbar.py").read_text()
    assert "unsaved_work" not in stock


# =============================================================================
# Telemetry: opaque ids and enums only, never in the way
# =============================================================================

@pytest.fixture
def sent(monkeypatch):
    from mixar.modules.common.analytics import recovery_events as RE
    events = []
    monkeypatch.setattr(RE, "capture", lambda event, props=None, **kw: events.append((event, props)))
    RE.reset()
    yield events
    RE.reset()


def _secret_offer(tmp_path):
    return {"session": "20261103T101010-42-abc123", "app_session_id": "app-uuid",
            "dir": str(tmp_path / "recovery" / "x"), "failed_points": ["/Users/me/sp-2.mixar"],
            "loop": True, "name": "secret-castle",
            "target": {"kind": "snapshot", "path": "/Users/me/secret-castle.mixar", "at": NOW,
                       "original_path": "/Users/me/secret-castle.mixar",
                       "scenes": ["My Private Scene", "B"],
                       "agent_scenes": [{"scene": "My Private Scene", "session_id": "chat-sid"}],
                       "jobs": [{"label": "a prompt the user typed"}]}}


def test_recovery_events_carry_only_allowlisted_opaque_properties(sent, tmp_path, monkeypatch):
    from mixar.modules.common.analytics import recovery_events as RE
    monkeypatch.setattr(RE.time, "time", lambda: NOW + 90)
    RE.track("requested", _secret_offer(tmp_path), surface="splash")
    RE.track("failed", {"session": "s"}, surface="somewhere", failure_category="/a/path")
    RE.track("not_a_stage", _secret_offer(tmp_path))
    (event, props), (event2, props2) = sent
    assert event == "session_recovery.requested"
    assert props == {"recovery_session_id": "20261103T101010-42-abc123",
                     "crashed_app_session_id": "app-uuid", "candidate_kind": "turn_checkpoint",
                     "snapshot_age_s": 90, "tabs_count": 2, "attempt": 2, "crash_loop": True,
                     "surface": "splash"}
    assert props2 == {"recovery_session_id": "s", "crashed_app_session_id": None,
                      "surface": "other", "failure_category": "other"}
    text = repr(sent)
    for leak in ("/Users", "secret-castle", "Private", "chat-sid", "prompt"):
        assert leak not in text


def test_a_failing_save_point_is_reported_at_most_every_ten_minutes(sent, monkeypatch):
    from mixar.modules.common.analytics import recovery_events as RE
    clock = [1000.0]
    monkeypatch.setattr(RE.time, "monotonic", lambda: clock[0])
    RE.track("save_point_failed", failure_category="write_failed")
    clock[0] += 60
    RE.track("save_point_failed", failure_category="write_failed")
    clock[0] += RE.SAVE_POINT_FAILED_INTERVAL_S
    RE.track("save_point_failed", failure_category="not_filed")
    assert [p["failure_category"] for _, p in sent] == ["write_failed", "not_filed"]


def test_telemetry_that_raises_never_breaks_a_restore(rt, tmp_path, monkeypatch):
    from mixar.modules.common.analytics import recovery_events as RE

    def boom(*a, **kw):
        raise RuntimeError("telemetry down")
    monkeypatch.setattr(RE, "capture", boom)
    monkeypatch.setattr(RE, "offer_properties", boom)
    point = _file(tmp_path / "recovery" / "old" / "sp-1.mixar")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "old", "dir": "", "legacy": False, "failed_points": [], "older": [], "debris": [],
        "target": {"kind": "save_point", "path": point, "at": NOW, "original_path": ""}})
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save", lambda filepath: {'FINISHED'}, raising=False)
    import mixar.modules.space_mixie_chat.core.checkpoint_timeline as ct
    monkeypatch.setattr(ct, "_retitle", lambda path: None)
    monkeypatch.setattr(ct, "_keep_modified", lambda path: (lambda: None))
    assert rt.restore_deferred("dialog")
    rt._restore_now()
    assert rt._state["restore_target"]["path"] == point
    monkeypatch.setattr(rt.bpy.ops.wm, "save_auto_save", lambda: {'CANCELLED'}, raising=False)
    assert rt.write_save_point(["timer"]) is None


def _restore_flow(rt, tmp_path, monkeypatch, *, read, jobs_left=0):
    point = _file(tmp_path / "recovery" / "old" / "sp-1.mixar")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "old", "app_session_id": "app-1", "dir": "", "legacy": False,
        "failed_points": [], "older": [], "debris": [],
        "target": {"kind": "save_point", "path": point, "at": NOW, "original_path": "",
                   "scenes": ["A"], "agent_scenes": [], "jobs": []}})
    monkeypatch.setattr(rt.bpy.ops.wm, "recover_auto_save", lambda filepath: read, raising=False)
    import mixar.modules.space_mixie_chat.core.checkpoint_timeline as ct
    monkeypatch.setattr(ct, "_retitle", lambda path: None)
    monkeypatch.setattr(ct, "_keep_modified", lambda path: (lambda: None))
    monkeypatch.setattr(rt, "_report", lambda text: None)
    monkeypatch.setattr(rt, "_adopt_jobs", lambda records: jobs_left)
    from types import SimpleNamespace
    monkeypatch.setattr(rt, "_session_manager", lambda: SimpleNamespace(is_connected=lambda s: False))
    assert rt.restore_deferred("splash")
    rt._restore_now()
    if 'FINISHED' in read:
        rt._after_restore()


def test_a_restore_reports_requested_restored_and_completed(rt, sent, tmp_path, monkeypatch):
    _restore_flow(rt, tmp_path, monkeypatch, read={'FINISHED'})
    assert [e for e, _ in sent] == ["session_recovery.requested", "session_recovery.scene_restored",
                                    "session_recovery.completed"]
    assert all(p["surface"] == "splash" and p["recovery_session_id"] == "old"
               and p["crashed_app_session_id"] == "app-1" for _, p in sent)


def test_a_restore_that_leaves_generations_behind_is_partial(rt, sent, tmp_path, monkeypatch):
    _restore_flow(rt, tmp_path, monkeypatch, read={'FINISHED'}, jobs_left=2)
    assert sent[-1][0] == "session_recovery.partial"
    assert sent[-1][1]["failure_category"] == "jobs_not_reattached"


def test_a_read_that_fails_is_reported(rt, sent, tmp_path, monkeypatch):
    _restore_flow(rt, tmp_path, monkeypatch, read={'CANCELLED'})
    assert [e for e, _ in sent] == ["session_recovery.requested", "session_recovery.failed"]
    assert sent[-1][1]["failure_category"] == "read_cancelled"


def test_start_fresh_and_a_failed_save_point_are_reported(rt, sent, tmp_path, monkeypatch):
    crashed = _session(tmp_path, "crashed")
    monkeypatch.setitem(rt._state, "offer", {
        "session": "crashed", "dir": crashed["dir"], "legacy": False, "failed_points": [],
        "debris": [], "older": [], "target": {"kind": "autosave", "path": "p", "at": NOW}})
    rt.discard_offer("dialog")
    monkeypatch.setattr(rt.bpy.ops.wm, "save_auto_save", lambda: {'CANCELLED'}, raising=False)
    rt.write_save_point(["timer"])
    rt.write_save_point(["timer"])                  # rate limited
    assert [(e, p.get("surface"), p.get("failure_category")) for e, p in sent] == [
        ("session_recovery.dismissed", "dialog", None),
        ("session_recovery.save_point_failed", None, "write_failed")]


def test_each_crash_is_reported_once_and_the_offer_every_launch(sent, tmp_path):
    from mixar.modules.session_recovery import telemetry
    a = _crashed(tmp_path, "a", NOW - 60)
    b = _crashed(tmp_path, "b", NOW - 600)
    debris = _session(tmp_path, "debris")
    sessions = journal.list_sessions(str(tmp_path / "recovery"), alive=lambda d: False)
    offer = decision.find_offer(sessions, now=NOW)
    assert offer["session"] == "a" and offer["debris"] == [debris["dir"]]
    telemetry.report_startup(offer, offer)
    telemetry.report_startup(offer, offer)          # the next launch, nothing answered
    names = [(e, p["recovery_session_id"]) for e, p in sent]
    assert names == [("session_recovery.unclean_exit_detected", "a"),
                     ("session_recovery.unclean_exit_detected", "b"),
                     ("session_recovery.unclean_exit_detected", "debris"),
                     ("session_recovery.available", "a"),
                     ("session_recovery.available", "a")]
    assert journal.read_manifest(a["dir"])["unclean_exit_reported"] is True
    assert journal.read_manifest(b["dir"])["unclean_exit_reported"] is True


def test_the_journal_names_its_process_for_the_next_launch(tmp_path):
    jr = journal.Journal(str(tmp_path / "recovery"), pid=1, now=NOW, app_session_id="app-9")
    assert journal.read_manifest(jr.dir)["app_session_id"] == "app-9"
    s = _crashed(tmp_path, "x", NOW - 5, app_session_id="app-7")
    assert decision.find_offer([s], now=NOW)["app_session_id"] == "app-7"


def test_continue_events_carry_only_allowlisted_outcomes(sent):
    from mixar.modules.common.analytics import recovery_events as RE
    RE.track("continue_finished", {"session": "s"}, surface="chat", outcome="cancelled", duration_s=12.7)
    RE.track("continue_finished", {"session": "s"}, surface="chat", outcome="/Users/me", duration_s=-3)
    RE.track("continue_offered", {"session": "s"}, surface="chat", reshown=True)
    (_, first), (_, second), (event, third) = sent
    assert first["outcome"] == "cancelled" and first["duration_s"] == 12 and first["surface"] == "chat"
    assert second["outcome"] == "other" and second["duration_s"] == 0
    assert event == "session_recovery.continue_offered" and third["reshown"] is True


def test_a_continued_turn_reports_how_it_ended(rt, sent, monkeypatch):
    clock = [500.0]
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock[0])
    monkeypatch.setitem(rt._state, "offer", {"session": "rec-1", "app_session_id": "app-1"})
    monkeypatch.setitem(rt._continue_sent, "cmd-1", ("chat-sid", NOW, 500.0))
    clock[0] = 666.0
    rt.continue_turn_ended("cmd-1", "completed")
    rt.continue_turn_ended("cmd-1", "completed")      # once per Continue
    rt.continue_turn_ended("another-turn", "failed")  # not a crash Continue
    assert [(e, p["outcome"], p["duration_s"], p["recovery_session_id"]) for e, p in sent] == [
        ("session_recovery.continue_finished", "completed", 166, "rec-1")]


def test_a_refused_continue_is_reported_and_never_finishes(rt, sent, monkeypatch):
    monkeypatch.setitem(rt._state, "offer", {"session": "rec-1"})
    monkeypatch.setitem(rt._continue_sent, "cmd-2", ("chat-sid", NOW, 1.0))
    rt.continue_refused(None, "cmd-2")
    rt.continue_turn_ended("cmd-2", "completed")
    assert [e for e, _ in sent] == ["session_recovery.continue_refused"]
