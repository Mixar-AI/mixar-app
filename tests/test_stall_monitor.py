# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Main-thread stall monitor: `WM_main` phase timing, breadcrumb hooks, log reader.

Pins the native wiring at source level (the C++ is not importable here) and
exercises the Python reader on representative records.
"""

from pathlib import Path

from mixar.modules.common.utils import stall_log

ROOT = Path(__file__).resolve().parents[1]
WM = ROOT / "src/source/blender/windowmanager"
PY = ROOT / "src/source/blender/python/intern"


def test_main_loop_times_every_phase():
    cc = (WM / "intern/wm.cc").read_text()
    loop = cc[cc.index("void WM_main(bContext *C)"):]
    assert loop.index("Mixar_stall_iteration_begin();") < loop.index("wm_window_events_process(C);")
    for call, phase in (
        ("wm_window_events_process(C);", "MIXAR_STALL_PHASE_EVENTS"),
        ("wm_event_do_handlers(C);", "MIXAR_STALL_PHASE_HANDLERS"),
        ("wm_event_do_notifiers(C);", "MIXAR_STALL_PHASE_NOTIFIERS"),
        ("wm_draw_update(C);", "MIXAR_STALL_PHASE_DRAW"),
    ):
        assert loop.index(call) < loop.index(f"Mixar_stall_phase_end({phase});")
    assert loop.index("Mixar_stall_iteration_end(C);") > loop.index("MIXAR_STALL_PHASE_DRAW")


def test_breadcrumbs_cover_the_known_entry_points():
    ev = (WM / "intern/wm_event_system.cc").read_text()
    assert ev.count('Mixar_StallScope stall_scope("op", op->type->idname);') == 4
    assert 'Mixar_StallScope stall_scope("modal", ot->idname);' in ev
    assert 'Mixar_stall_scope_push("op", handler->op->type->idname);' in ev   # file-select exec
    assert ev.count('"depsgraph"') == 2
    assert ev.count('Mixar_StallScope stall_scope("undo_push", ') == 3
    assert 'Mixar_StallScope stall_scope("ui", stall_name);' in ev
    assert 'Mixar_StallScope stall_scope("area_refresh", ' in ev
    assert 'Mixar_StallScope stall_scope("msgbus", "WM_msgbus_handle");' in ev
    assert 'Mixar_StallScope stall_scope("undo_push", op->type->idname);' in (
        WM / "intern/wm_operators.cc").read_text()
    draw = (WM / "intern/wm_draw.cc").read_text()
    assert draw.count('Mixar_StallScope stall_scope("draw", stall_name);') == 2   # areas + menus
    assert 'Mixar_StallScope stall_scope("layout", stall_name);' in draw
    jobs = (WM / "intern/wm_jobs.cc").read_text()
    for kind in ("job_tick", "job_end", "job_kill"):
        assert f'Mixar_StallScope stall_scope("{kind}", ' in jobs
    assert 'Mixar_StallScope stall_scope("autosave", "wm_autosave_timer");' in (
        WM / "intern/wm_files.cc").read_text()
    assert 'Mixar_StallScope stall_scope("window", ' in draw and '"gpu", "GPU_render_step"' in draw
    window = (WM / "intern/wm_window.cc").read_text()
    assert 'Mixar_StallScope stall_scope("window_open", ' in window
    assert 'Mixar_StallScope stall_scope("os_resize", ' in window
    assert 'Mixar_StallScope stall_scope("screen_refresh", ' in window
    cache = (PY / "bpy_mixar_stall.hh").read_text()
    assert "static Entry cache[CACHE_MAX];" in cache and "Py_INCREF(callable);" in cache
    assert 'Mixar_stall_scope_push("timer", stall_name)' in (PY / "bpy_app_timers.cc").read_text()
    assert 'Mixar_stall_scope_push("handler", stall_name)' in (PY / "bpy_app_handlers.cc").read_text()
    assert 'Mixar_stall_scope_push("draw_cb", stall_name)' in (PY / "bpy_rna_callback.cc").read_text()


def test_monitor_is_main_thread_only_and_registered():
    mon = (WM / "intern/wm_stall_monitor.cc").read_text()
    assert "if (ms < 1.0) {" in mon[mon.index("void record_top("):]
    push = mon[mon.index("int Mixar_stall_scope_push("):mon.index("void Mixar_stall_scope_pop(")]
    assert "!BLI_thread_is_main()" in push
    assert '"MIXAR_STALL_THRESHOLD_MS"' in mon and '"MIXAR_STALL_LOG"' in mon and '"MIXAR_STALL_PRINT"' in mon
    assert 'BLI_path_join(path, sizeof(path), dir->c_str(), "stalls.jsonl");' in mon
    assert "LOG_ROTATE_BYTES" in mon and "BLI_rename_overwrite" in mon
    cmake = (WM / "CMakeLists.txt").read_text()
    assert "intern/wm_stall_monitor.cc" in cmake and "WM_stall_monitor.hh" in cmake
    assert "bpy_mixar_stall.hh" in (PY / "CMakeLists.txt").read_text()


RECORDS = [
    '{"t":"2026-10-12T09:30:01Z","up":12.0,"seq":1,"ms":812,"ph":[1,790,2,19],"job":0,"scopes":3,'
    '"top":[{"k":"timer","n":"m.tick","ms":790,"d":0},{"k":"op","n":"wm.save_as_mainfile","ms":780,"d":1}],'
    '"n":{"timer":1,"op":1,"draw":1}}',
    '{"t":"2026-10-12T09:30:05Z","up":16.0,"seq":2,"ms":140,"ph":[2,3,1,134],"job":1,"scopes":0,"top":[],"n":{}}',
    'garbage {not json',
    '{"t":"2026-10-12T09:30:09Z","up":20.0,"seq":3,"ms":300,"ph":[1,290,2,7],"job":0,"scopes":1,'
    '"top":[{"k":"timer","n":"m.tick","ms":290,"d":0}],"n":{"timer":1}}',
]


def test_reader_parses_filters_and_summarises(tmp_path, monkeypatch):
    path = tmp_path / "stalls.jsonl"
    path.write_text("\n".join(RECORDS) + "\n")
    monkeypatch.setenv("MIXAR_STALL_LOG", str(path))
    assert stall_log.stall_log_path() == str(path)
    records = stall_log.read_stalls()
    assert [r["seq"] for r in records] == [1, 2, 3]                  # torn line skipped
    assert [r["seq"] for r in stall_log.read_stalls(since_seq=2)] == [3]
    assert stall_log.culprit(records[0]) == "op:wm.save_as_mainfile"   # deepest crumb that explains it
    assert stall_log.culprit(records[1]) == "phase:draw"             # no breadcrumb ran
    summary = stall_log.summarize(records)
    assert summary[0] == {"culprit": "op:wm.save_as_mainfile", "count": 1, "total_ms": 812, "max_ms": 812}
    assert [g["culprit"] for g in summary[1:]] == ["timer:m.tick", "phase:draw"]
    assert stall_log.read_stalls(str(tmp_path / "missing.jsonl")) == []
