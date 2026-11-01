# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The render worker supervisor against real child processes.

``fake_worker.py`` speaks the worker protocol from plain Python, so the
process lifecycle is exercised for real: a warm worker reused, a native crash
(SIGSEGV) retried once on a fresh worker, a second crash failing the job, boot
failures disabling the worker path for the session, timeouts and cancels
killing the process, idle workers stopped. The Blender side (snapshot, render,
export in the worker) is proven in the built app through the QA harness.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.common.render_worker import protocol, supervisor

HERE = Path(__file__).resolve().parent
PROTOCOL = Path(protocol.__file__).resolve()


@pytest.fixture
def sup(monkeypatch, tmp_path):
    supervisor.reset_for_tests()
    monkeypatch.setattr(supervisor, "_parent_dir", lambda: str(tmp_path))
    monkeypatch.setattr(supervisor, "_binary_path", lambda: sys.executable)
    monkeypatch.setattr(supervisor, "_argv",
                        lambda: [sys.executable, str(HERE / "fake_worker.py"), str(PROTOCOL)])
    monkeypatch.setattr(supervisor, "_ensure_maintenance", lambda: None)
    monkeypatch.delenv("FAKE_BOOT", raising=False)
    yield supervisor
    supervisor.reset_for_tests()


def _job(tmp_path, name="a", mode="ok"):
    return {"kind": "preview", "snapshot": "unused.blend", "scene": "Scene", "view_layer": "",
            "params": {"mode": mode, "name": name}, "out": str(tmp_path / (name + ".json"))}


def _wait(sup, job_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = sup.poll(job_id)
        if state["state"] not in ("queued", "running"):
            return state
        time.sleep(0.02)
    raise AssertionError("job did not settle: %r" % sup.poll(job_id))


def _dead(pid, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        try:  # reap if it is our zombie child
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return True
        except ChildProcessError:
            pass
        time.sleep(0.05)
    return False


def test_marker_is_found_after_blender_noise_on_the_same_line():
    line = "Fra:1 Mem:12M" + protocol.encode({"type": "ready", "pid": 3})
    assert protocol.decode(line) == {"type": "ready", "pid": 3}
    assert protocol.decode("plain blender output\n") is None
    assert protocol.decode(protocol.MARK + "{broken") is None


def test_a_job_runs_and_the_warm_worker_serves_the_next(sup, tmp_path):
    first = sup.submit("preview", _job(tmp_path, "a"), timeout_s=10)
    state = _wait(sup, first)
    assert state["state"] == "done" and state["attempts"] == 1
    assert json.loads(Path(state["out"]).read_text())["echo"]["name"] == "a"
    second = sup.submit("preview", _job(tmp_path, "b"), timeout_s=10)
    again = _wait(sup, second)
    assert again["state"] == "done"
    assert again["pid"] == state["pid"], "the warm worker is reused"


def test_a_crash_is_retried_once_on_a_fresh_worker(sup, tmp_path):
    sup.crash_next("preview", 1)
    job = sup.submit("preview", _job(tmp_path), timeout_s=10)
    state = _wait(sup, job)
    assert state["state"] == "done"
    assert state["attempts"] == 2 and state["retried_after_crash"]
    assert sup.available(), "a crash in a job never disables the worker path"


def test_a_second_crash_fails_the_job_and_nothing_else(sup, tmp_path):
    sup.crash_next("preview", 2)
    job = sup.submit("preview", _job(tmp_path), timeout_s=10)
    state = _wait(sup, job)
    assert state == dict(state, state="failed", error="worker_crashed", attempts=2)
    following = _wait(sup, sup.submit("preview", _job(tmp_path, "next"), timeout_s=10))
    assert following["state"] == "done"


def test_a_worker_that_cannot_boot_falls_back_and_disables_the_path(sup, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_BOOT", "fail")
    state = _wait(sup, sup.submit("preview", _job(tmp_path), timeout_s=10))
    assert state["state"] == "failed" and state["error"] == "worker_unavailable"
    assert state["attempts"] == 0, "the job never ran"
    assert not sup.available() and sup.disabled_reason() == "boot_failed"


def test_a_worker_that_never_reports_ready_is_killed(sup, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_BOOT", "hang")
    monkeypatch.setattr(sup, "BOOT_TIMEOUT_S", 0.3)
    state = _wait(sup, sup.submit("preview", _job(tmp_path), timeout_s=10))
    assert state["error"] == "worker_unavailable"
    assert not sup.workers()


def test_a_job_over_its_deadline_is_killed_with_its_worker(sup, tmp_path):
    job = sup.submit("preview", _job(tmp_path, mode="hang"), timeout_s=0.3)
    state = _wait(sup, job)
    assert state["error"] == "worker_timeout"
    assert _dead(state["pid"])


def test_cancel_kills_the_worker_running_the_job(sup, tmp_path):
    job = sup.submit("preview", _job(tmp_path, mode="hang"), timeout_s=30)
    deadline = time.monotonic() + 5
    while not sup.workers().get("preview", {}).get("ready") and time.monotonic() < deadline:
        sup.maintain()
        time.sleep(0.02)
    pid = sup.poll(job)["pid"]
    sup.cancel(job)
    assert sup.poll(job)["state"] == "cancelled"
    assert _dead(pid)
    assert _wait(sup, sup.submit("preview", _job(tmp_path, "after"), timeout_s=10))["state"] == "done"


def test_a_failed_job_keeps_its_worker(sup, tmp_path):
    state = _wait(sup, sup.submit("preview", _job(tmp_path, mode="fail"), timeout_s=10))
    assert state["state"] == "failed" and state["error"] == "worker_job_failed"
    assert sup.workers()["preview"]["alive"]


def test_an_idle_worker_is_stopped(sup, tmp_path, monkeypatch):
    state = _wait(sup, sup.submit("preview", _job(tmp_path), timeout_s=10))
    monkeypatch.setattr(sup, "IDLE_TTL_S", 0.0)
    sup.maintain()
    assert not sup.workers()
    assert _dead(state["pid"])


def test_shutdown_kills_every_worker_and_removes_the_session_folder(sup, tmp_path):
    state = _wait(sup, sup.submit("preview", _job(tmp_path), timeout_s=10))
    folder = Path(sup.root_dir())
    assert folder.is_dir()
    sup.shutdown_all(remove_files=True)
    assert _dead(state["pid"])
    assert not folder.exists()


def test_stale_folders_of_dead_sessions_are_swept(sup, tmp_path, monkeypatch):
    stale = tmp_path / "999999"
    stale.mkdir()
    monkeypatch.setattr(sup, "_swept", False)
    monkeypatch.setattr(sup, "_pid_alive", lambda pid, since=0.0: pid != 999999)
    sup.root_dir()
    assert not stale.exists()


def test_an_old_folder_of_a_live_session_is_never_swept(sup, tmp_path, monkeypatch):
    """A second instance must not delete a long-running instance's worker
    folder: only a dead pid is swept, however old the folder is."""
    live = tmp_path / "424242"
    (live / "worker-preview" / "tmp").mkdir(parents=True)
    os.utime(live, (time.time() - 3 * 86400, time.time() - 3 * 86400))
    monkeypatch.setattr(sup, "_swept", False)
    monkeypatch.setattr(sup, "_pid_alive", lambda pid, since=0.0: True)
    sup.root_dir()
    assert live.exists()


# --------------------------------------------------------------------------
# Worker crash reports survive the worker folder
# --------------------------------------------------------------------------

@pytest.fixture
def crash_dir(monkeypatch, tmp_path):
    folder = tmp_path / "crashes"
    monkeypatch.setattr(supervisor, "crash_dir", lambda: str(folder))
    return folder


def _crash_file(worker_folder, name="mixar_worker_snapshot_1.crash.txt", text="# Blender crash\n"):
    tmp = Path(worker_folder) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / name).write_text(text)
    return tmp / name


def test_the_crash_folder_name_is_the_contract_with_the_crash_reporter():
    assert supervisor.CRASH_DIR_NAME == "mixar_render_worker_crashes"
    import tempfile
    assert supervisor.crash_dir() == os.path.join(tempfile.gettempdir(), "mixar_render_worker_crashes")


def test_a_crash_report_is_moved_without_overwriting(tmp_path, crash_dir):
    worker = tmp_path / "123" / "worker-preview"
    (crash_dir).mkdir()
    (crash_dir / "123-preview-1.crash.txt").write_text("earlier")
    original = _crash_file(worker, text="new crash")
    kept = supervisor._keep_crash_reports(str(worker), "123", "preview")
    assert [Path(p).name for p in kept] == ["123-preview-2.crash.txt"]
    assert (crash_dir / "123-preview-1.crash.txt").read_text() == "earlier"
    assert (crash_dir / "123-preview-2.crash.txt").read_text() == "new crash"
    assert not original.exists()
    assert supervisor._keep_crash_reports(str(worker), "123", "preview") == []


def _dump(worker_folder, pid, text="Fatal Python error: Segmentation fault\n\n", mtime=None):
    tmp = Path(worker_folder) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / ("pyfault-%d.txt" % pid)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_the_faulthandler_dump_moves_beside_its_crash_report(tmp_path, crash_dir):
    worker = tmp_path / "123" / "worker-preview"
    now = time.time()
    crash = _crash_file(worker, text="new crash")
    os.utime(crash, (now, now))
    crashed = _dump(worker, 501, text="Fatal Python error: Segmentation fault\n\nCurrent thread 0x1", mtime=now)
    killed = _dump(worker, 500, text="", mtime=now)  # an earlier worker, killed: an empty dump
    older = _dump(worker, 499, mtime=now - 3600)  # an earlier crash's leftover
    kept = supervisor._keep_crash_reports(str(worker), "123", "preview")
    assert [Path(p).name for p in kept] == ["123-preview-1.crash.txt"]
    assert (crash_dir / "123-preview-1.pyfault.txt").read_text().endswith("Current thread 0x1")
    assert not crashed.exists() and killed.exists() and older.exists()


def test_a_dump_without_a_crash_report_is_kept_alone_on_macos_only(tmp_path, crash_dir, monkeypatch):
    worker = tmp_path / "123" / "worker-render"
    (crash_dir).mkdir()
    (crash_dir / "123-render-1.crash.txt").write_text("earlier")
    _dump(worker, 501, text="Fatal Python error: Aborted\n\n")
    empty = _dump(worker, 502, text="")
    monkeypatch.setattr(supervisor.sys, "platform", "win32")
    assert supervisor._keep_crash_reports(str(worker), "123", "render") == []
    assert sorted(p.name for p in crash_dir.iterdir()) == ["123-render-1.crash.txt"]
    monkeypatch.setattr(supervisor.sys, "platform", "darwin")
    assert supervisor._keep_crash_reports(str(worker), "123", "render") == []  # no crash log moved
    assert (crash_dir / "123-render-2.pyfault.txt").read_text().startswith("Fatal Python error: Aborted")
    assert empty.exists()
    # The next crash report skips the number the lone dump holds.
    _crash_file(worker, text="next crash")
    kept = supervisor._keep_crash_reports(str(worker), "123", "render")
    assert [Path(p).name for p in kept] == ["123-render-3.crash.txt"]


def test_quit_keeps_the_dump_with_the_crash_report(sup, tmp_path, crash_dir):
    session = Path(sup.root_dir())
    _crash_file(session / "worker-export", text="unseen crash")
    _dump(session / "worker-export", 777)
    sup.shutdown_all(remove_files=True)
    assert not session.exists()
    assert (crash_dir / ("%d-export-1.pyfault.txt" % os.getpid())).exists()


@pytest.mark.skipif(not hasattr(signal, "SIGSEGV"), reason="POSIX signal")
def test_a_crashed_worker_keeps_its_report_before_the_retry(sup, tmp_path, crash_dir, monkeypatch):
    seen = {}
    real = sup._keep_crash_reports

    def keep(folder, session, kind):
        if not seen:  # the first death: the worker wrote its report as it died
            _crash_file(folder, text="first crash")
        seen.setdefault("calls", []).append((session, kind))
        return real(folder, session, kind)

    monkeypatch.setattr(sup, "_keep_crash_reports", keep)
    sup.crash_next("preview", 1)
    state = _wait(sup, sup.submit("preview", _job(tmp_path), timeout_s=10))
    assert state["state"] == "done" and state["retried_after_crash"]
    assert seen["calls"][0] == (str(os.getpid()), "preview")
    kept = sorted(crash_dir.glob("*.crash.txt"))
    assert [p.name for p in kept] == ["%d-preview-1.crash.txt" % os.getpid()]
    assert kept[0].read_text() == "first crash"


def test_quit_keeps_crash_reports_before_removing_the_session_folder(sup, tmp_path, crash_dir):
    session = Path(sup.root_dir())
    _crash_file(session / "worker-export", text="unseen crash")
    sup.shutdown_all(remove_files=True)
    assert not session.exists()
    assert (crash_dir / ("%d-export-1.crash.txt" % os.getpid())).read_text() == "unseen crash"


def test_the_stale_sweep_keeps_crash_reports_of_dead_sessions(sup, tmp_path, crash_dir, monkeypatch):
    stale = tmp_path / "999999"
    _crash_file(stale / "worker-preview", text="last session's crash")
    monkeypatch.setattr(sup, "_swept", False)
    monkeypatch.setattr(sup, "_pid_alive", lambda pid, since=0.0: pid != 999999)
    sup.root_dir()
    assert not stale.exists()
    assert (crash_dir / "999999-preview-1.crash.txt").read_text() == "last session's crash"


# --------------------------------------------------------------------------
# Windows liveness (ctypes mocked)
# --------------------------------------------------------------------------

def _fake_kernel32(monkeypatch, *, handle=1, last_error=0, exit_code=259, created_unix=None):
    import ctypes
    closed = []

    def exit_code_of(h, code_ref):
        code_ref._obj.value = exit_code
        return 1

    def times_of(h, created, *rest):
        if created_unix is None:
            return 0
        ticks = int(created_unix * 1e7) + 116444736000000000
        created._obj.dwHighDateTime, created._obj.dwLowDateTime = ticks >> 32, ticks & 0xFFFFFFFF
        return 1

    def kernel32():
        # Plain functions, so the code under test can set argtypes / restype.
        return SimpleNamespace(OpenProcess=lambda access, inherit, pid: handle,
                               CloseHandle=lambda h: closed.append(h) or 1,
                               GetExitCodeProcess=lambda h, ref: exit_code_of(h, ref),
                               GetProcessTimes=lambda h, *refs: times_of(h, *refs))

    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: kernel32(), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error, raising=False)
    import ctypes.wintypes  # noqa: F401 — importable on every platform
    return closed


def test_windows_a_running_process_is_alive(monkeypatch):
    closed = _fake_kernel32(monkeypatch)
    assert supervisor._windows_pid_alive(4321) is True
    assert closed == [1], "the handle is closed"


def test_windows_an_exited_process_is_dead(monkeypatch):
    _fake_kernel32(monkeypatch, exit_code=0)
    assert supervisor._windows_pid_alive(4321) is False


def test_windows_no_such_process_is_dead_and_access_denied_is_alive(monkeypatch):
    _fake_kernel32(monkeypatch, handle=None, last_error=87)
    assert supervisor._windows_pid_alive(4321) is False
    _fake_kernel32(monkeypatch, handle=None, last_error=5)
    assert supervisor._windows_pid_alive(4321) is True


def test_windows_a_pid_reused_by_a_younger_process_is_dead(monkeypatch):
    folder_created = time.time() - 3600
    _fake_kernel32(monkeypatch, created_unix=folder_created + 600)
    assert supervisor._windows_pid_alive(4321, since=folder_created) is False
    _fake_kernel32(monkeypatch, created_unix=folder_created - 600)
    assert supervisor._windows_pid_alive(4321, since=folder_created) is True


def test_windows_liveness_that_cannot_be_read_is_alive(monkeypatch):
    def broken(pid, since=0.0):
        raise OSError("no kernel32")
    monkeypatch.setattr(supervisor.os, "name", "nt")
    monkeypatch.setattr(supervisor, "_windows_pid_alive", broken)
    assert supervisor._pid_alive(4321) is True


def test_unknown_kinds_are_refused(sup, tmp_path):
    with pytest.raises(ValueError):
        sup.submit("render_everything", _job(tmp_path), timeout_s=1)


@pytest.mark.skipif(not hasattr(signal, "SIGSEGV"), reason="POSIX signal")
def test_the_crash_hook_is_one_shot_per_count(sup, tmp_path):
    sup.crash_next("export", 1)
    job = sup.submit("export", dict(_job(tmp_path), kind="export"), timeout_s=10)
    assert _wait(sup, job)["attempts"] == 2
    assert _wait(sup, sup.submit("export", dict(_job(tmp_path, "x"), kind="export"),
                                 timeout_s=10))["attempts"] == 1
