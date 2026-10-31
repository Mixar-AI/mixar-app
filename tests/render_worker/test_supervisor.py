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
    monkeypatch.setattr(sup, "_pid_alive", lambda pid: pid != 999999)
    sup.root_dir()
    assert not stale.exists()


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
