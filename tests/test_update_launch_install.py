# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install at launch (issue 2079): an update staged by a session that never
quit normally (a crash, a force quit, a kill) is recognised from its staged
record — no re-download, no re-hash — and installed before the user starts
working, unless anything says not to. Also the reopen request a launch
turned away by a running helper leaves behind, and the staged record.
What it must never install (an old download, an unoffered release, an
unverified signature) is in ``test_update_launch_install_trust.py``.
"""

import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from update_launch_fixtures import HELPER_PID, FakeTimers, _begin, _record
from update_launch_fixtures import staged_fixture  # noqa: F401 - the `staged` fixture

import pytest

from mixar.bootstrap import update_checker as boot
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import (
    HELPER_MARKER_NAME,
    HELPER_REOPEN_NAME,
    HELPER_RESULT_NAME,
    STAGED_RECORD_NAME,
    UPDATE_NOTIFICATION_ID,
)
from mixar.modules.common.updates.core import (
    app_paths,
    install_gate,
    install_marker,
    install_start,
    installer,
    launch_install,
    staged_record,
    update_checker,
)

# ---------------------------------------------------------------------------
# Is there anything to install at this launch?
# ---------------------------------------------------------------------------


def test_a_staged_update_from_a_crashed_session_is_found(staged):
    request = launch_install.launch_install_request()

    assert request["record"]["version"] == "3.4.0"
    assert request["directory"] == str(staged.directory)
    # Eligibility is judged from the record: no update check has run yet.
    info = staged.info[-1]
    assert (info.latest_version, info.installer_type) == ("3.4.0", "dmg")
    assert info.download_sha256 == "a" * 64 and info.download_url


def test_it_is_asked_once_per_process(staged):
    assert launch_install.launch_install_request() is not None
    assert launch_install.launch_install_request() is None  # a script reload


@pytest.mark.parametrize("case", [
    "background", "setting_off", "recovery_offer", "opened_with_file",
    "result_unread", "tried_at_launch", "installer_changed", "needs_elevation",
    "blocked", "failed_before", "running_unknown",
])
def test_it_stands_down(staged, monkeypatch, case):
    if case == "background":
        staged.bpy.app.background = True
    elif case == "setting_off":
        monkeypatch.setattr(launch_install, "install_on_quit_enabled", lambda: False)
    elif case == "recovery_offer":
        monkeypatch.setattr(launch_install, "_recovery_offer_pending", lambda: True)
    elif case == "opened_with_file":
        monkeypatch.setattr(launch_install, "_opened_with_file", lambda: True)
    elif case == "result_unread":
        (staged.directory / HELPER_RESULT_NAME).write_text("version=3.4.0\nstage=copy\nexit=1\n")
    elif case == "tried_at_launch":
        staged_record.bump(str(staged.directory), "launch_attempts", "3.4.0")
    elif case == "installer_changed":
        staged.dmg.write_bytes(b"something else")
    elif case == "needs_elevation":
        staged.location.needs_elevation = True
    elif case == "blocked":
        monkeypatch.setattr(install_gate, "silent_blocker", lambda e: "Mixar")
    elif case == "failed_before":
        for _ in range(2):
            staged_record.bump(str(staged.directory), "failures", "3.4.0")
    elif case == "running_unknown":
        monkeypatch.setattr(update_checker, "get_runtime_version", lambda: None)

    assert launch_install.launch_install_request() is None


def test_a_version_already_tried_at_launch_says_so(staged, monkeypatch):
    """One launch attempt per version: the refusal names the cap (RELEASE-15
    reads it from the app log), and the record keeps its single attempt."""
    staged_record.bump(str(staged.directory), "launch_attempts", "3.4.0")
    logger = MagicMock()
    monkeypatch.setattr(launch_install, "logger", logger)

    assert launch_install.launch_install_request() is None

    logger.info.assert_called_once_with(
        "Update %s not installed at launch: already tried at launch", "3.4.0")
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 1


def test_an_installed_version_retires_its_record(staged, monkeypatch):
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.4.0")

    assert launch_install.launch_install_request() is None
    assert not (staged.directory / STAGED_RECORD_NAME).exists()


def test_another_copy_s_download_is_left_alone(staged):
    """The staging directory is per user: a second copy of Mixar (a build
    beside the installed app) never installs the installed app's download."""
    _record(staged.directory, staged.dmg, target="/Users/u/build/Mixar.app")

    assert launch_install.launch_install_request() is None
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 0


def test_a_newer_second_copy_never_deletes_the_installed_copy_s_record(staged, monkeypatch):
    """A QA or dev build beside the installed app, newer than the installed
    app's download, leaves that download (and its record) alone."""
    monkeypatch.setattr(app_paths, "running_target", lambda: "/Users/u/build/Mixar.app")
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.5.0")

    assert launch_install.launch_install_request() is None
    assert staged_record.read(str(staged.directory))["version"] == "3.4.0"
    assert staged.dmg.exists()


def test_a_copy_that_cannot_tell_where_it_runs_judges_no_record(staged, monkeypatch):
    monkeypatch.setattr(app_paths, "running_target", lambda: "")
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.5.0")

    assert launch_install.launch_install_request() is None
    assert (staged.directory / STAGED_RECORD_NAME).exists()


def test_the_recovery_check_fails_closed(monkeypatch):
    import importlib

    # Patch both the module table and the package attribute: once any other
    # test has imported the real runtime, ``from pkg import runtime`` reads
    # the attribute and never consults sys.modules.
    broken = MagicMock(name="runtime")
    broken.current_offer.side_effect = RuntimeError("scan failed")
    package = importlib.import_module("mixar.modules.session_recovery")
    monkeypatch.setitem(sys.modules, "mixar.modules.session_recovery.runtime", broken)
    monkeypatch.setattr(package, "runtime", broken, raising=False)

    assert launch_install._recovery_offer_pending() is True


def test_a_file_on_the_command_line_is_the_user_s_work(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["Mixar", "/Users/u/scene.MIXAR"])
    assert launch_install._opened_with_file() is True
    monkeypatch.setattr(sys, "argv", ["Mixar", "--enable-event-simulate"])
    assert launch_install._opened_with_file() is False


# ---------------------------------------------------------------------------
# Installing: toast, a moment, re-check, helper, quit
# ---------------------------------------------------------------------------


def test_a_clean_launch_installs_and_quits(staged):
    resume = _begin(staged)

    launch_install._install()

    kwargs = staged.begin.call_args.kwargs
    assert kwargs["trigger"] == "launch" and kwargs["relaunch"] is True
    assert kwargs["installer_path"] == str(staged.dmg)
    assert kwargs["verified"] is True and kwargs["signer_thumbprint"] == "TEAM123"
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 1
    assert (staged.directory / HELPER_MARKER_NAME).exists()
    assert launch_install._quit in staged.timers.registered
    assert launch_install._quit_watchdog in staged.timers.registered
    launch_install._quit()
    staged.bpy.ops.wm.quit_blender.assert_called_once_with()
    resume.assert_not_called()


@pytest.mark.parametrize("change", [
    "file_opened", "edited", "restored", "another_mixar",
    # Started during the signature check (up to 120 s) or the 3 s toast:
    # session recovery's own detectors, which hold back a save point.
    "modal_or_script", "agent_turn", "generation", "busy_unknown",
    # Never quit under any modal, even one a save point may run under: an
    # asset train's background workers would die with Mixar.
    "passive_modal", "chat_draft",
])
def test_the_user_starting_work_cancels_it(staged, monkeypatch, change):
    from mixar.modules.common.job_queue.core import queue_manager
    from mixar.modules.session_recovery import runtime as recovery

    resume = _begin(staged)
    if change == "file_opened":
        staged.data.filepath = "/Users/u/scene.mixar"  # a Finder double-click
    elif change == "edited":
        staged.data.is_dirty = True
    elif change == "restored":
        monkeypatch.setattr(launch_install, "_recovery_offer_pending", lambda: True)
    elif change == "another_mixar":
        monkeypatch.setattr(install_gate, "silent_blocker", lambda e: "Mixar")
    elif change == "modal_or_script":
        monkeypatch.setattr(recovery, "_busy", lambda: True)
    elif change == "agent_turn":
        monkeypatch.setattr(recovery, "agent_scenes", lambda: [{"scene": "Scene", "session_id": "s"}])
    elif change == "passive_modal":
        assert "MIXIE_OT_train_asset_model" in recovery.PASSIVE_MODALS
        staged.window.modal_operators.append(
            SimpleNamespace(bl_idname="MIXIE_OT_train_asset_model"))
    elif change == "chat_draft":  # typed, not sent: not an undo step, not dirty
        staged.data.scenes[0].mixie_chat_input = "make the chair red"
    elif change == "generation":  # a Generate click: queued, not yet submitted
        monkeypatch.setattr(queue_manager, "active_queue_activity",
                            lambda: queue_manager.QueueActivity(1, "Image Gen", 1.0))
    else:
        def broken():
            raise RuntimeError("no window manager")

        monkeypatch.setattr(recovery, "_busy", broken)

    launch_install._install()

    staged.begin.assert_not_called()
    resume.assert_called_once_with()  # the normal start-up: report, update check
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 0


@pytest.mark.parametrize("change", ["file_opened", "edited"])
def test_work_started_during_the_checks_hears_nothing_about_quitting(staged, change):
    """The signature check and this launch's update check can take two
    minutes: a user who started meanwhile never sees "finishing an update"."""
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume,
                                        check_delay=5)
    if change == "file_opened":
        staged.data.filepath = "/Users/u/scene.mixar"
    else:
        staged.data.is_dirty = True
    launch_install._check_offer()

    assert launch_install._await_verdict() is None

    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)
    assert launch_install._install not in staged.timers.registered
    resume.assert_called_once_with()


def test_a_helper_that_cannot_start_resumes_the_launch_but_counts(staged):
    resume = _begin(staged)
    staged.begin.side_effect = OSError("no")

    launch_install._install()

    resume.assert_called_once_with()
    # Never tried at launch again, even though nothing ran.
    assert staged_record.read(str(staged.directory))["launch_attempts"] == 1


@pytest.mark.parametrize("case", ["unwritable", "taken"])
def test_an_attempt_that_cannot_be_counted_installs_nothing(staged, monkeypatch, case):
    """Never retried at every launch: a count that could not be written, or
    one another launch took first, starts no helper."""
    resume = _begin(staged)
    if case == "unwritable":
        monkeypatch.setattr(staged_record.os, "replace", MagicMock(side_effect=OSError("ro")))
    else:
        staged_record.bump(str(staged.directory), "launch_attempts", "3.4.0")

    launch_install._install()

    staged.begin.assert_not_called()
    resume.assert_called_once_with()
    if case == "unwritable":  # bump says so instead of returning the count it lost
        assert staged_record.bump(str(staged.directory), "failures", "3.4.0") == 0


def test_a_quit_that_never_happens_kills_the_helper(staged):
    resume = _begin(staged)
    launch_install._install()

    launch_install._quit_watchdog()

    staged.proc.kill.assert_called_once()
    assert not (staged.directory / HELPER_MARKER_NAME).exists()
    resume.assert_called_once_with()


def test_bootstrap_holds_the_update_check_while_installing(monkeypatch):
    timers = FakeTimers()
    fake = SimpleNamespace(app=SimpleNamespace(timers=timers,
                                               handlers=SimpleNamespace(exit_pre=[])))
    monkeypatch.setattr(boot, "bpy", fake)
    monkeypatch.setattr(boot, "_init_timer_registered", False)
    monkeypatch.setattr(boot, "_install_in_progress", lambda: False)
    request = {"record": {}}
    began = MagicMock()
    monkeypatch.setattr(launch_install, "launch_install_request", lambda: request)
    monkeypatch.setattr(launch_install, "begin_launch_install", began)
    # The launch's own update check waits as long as the normal one would.
    import mixar.config.config as config

    monkeypatch.setattr(boot, "_check_delay", 5)
    monkeypatch.setattr(config, "get_config", lambda: {"updates": {"check_delay_seconds": 7}})

    boot.register()

    assert boot._delayed_init not in timers.registered
    began.assert_called_once_with(request, resume=boot._schedule_delayed_init, check_delay=7)
    began.call_args.kwargs["resume"]()
    assert boot._delayed_init in timers.registered


# ---------------------------------------------------------------------------
# The launch a running helper turns away asks to be reopened
# ---------------------------------------------------------------------------


def test_a_turned_away_launch_leaves_its_pid_for_the_helper(staged, monkeypatch):
    record = {"helper_pid": HELPER_PID, "helper_created": None, "target_version": "3.4.0",
              "attempt_id": "a1", "written_at": time.time()}
    (staged.directory / HELPER_MARKER_NAME).write_text(json.dumps(record))
    monkeypatch.setattr(install_marker, "process_identity", lambda pid: (True, None))
    timers = FakeTimers()
    monkeypatch.setattr(boot, "bpy", SimpleNamespace(app=SimpleNamespace(timers=timers)))
    monkeypatch.setattr(boot, "_init_timer_registered", False)

    boot.register()

    assert boot._announce_and_quit in timers.registered
    assert (staged.directory / HELPER_REOPEN_NAME).read_text() == f"{os.getpid()}\n"
    install_marker.request_reopen(str(staged.directory), 77)
    assert (staged.directory / HELPER_REOPEN_NAME).read_text().split() == [
        str(os.getpid()), "77"]


def test_a_background_run_turned_away_mid_install_asks_for_no_reopen(staged, monkeypatch):
    """A `Mixar -b` started while an install on quit runs must not make the
    helper reopen the window the user just quit."""
    record = {"helper_pid": HELPER_PID, "helper_created": None, "target_version": "3.4.0",
              "attempt_id": "a1", "written_at": time.time()}
    (staged.directory / HELPER_MARKER_NAME).write_text(json.dumps(record))
    monkeypatch.setattr(install_marker, "process_identity", lambda pid: (True, None))
    timers = FakeTimers()
    monkeypatch.setattr(boot, "bpy", SimpleNamespace(app=SimpleNamespace(
        timers=timers, background=True)))
    monkeypatch.setattr(boot, "_init_timer_registered", False)

    boot.register()

    assert boot._announce_and_quit in timers.registered  # still turned away
    assert not (staged.directory / HELPER_REOPEN_NAME).exists()


def test_check_startup_says_where_the_marker_is(staged, monkeypatch):
    record = {"helper_pid": HELPER_PID, "helper_created": None, "target_version": "3.4.0",
              "attempt_id": "a1", "written_at": time.time()}
    (staged.directory / HELPER_MARKER_NAME).write_text(json.dumps(record))
    monkeypatch.setattr(install_marker, "process_identity", lambda pid: (True, None))

    found = install_marker.check_startup("3.3.6")

    assert found["directory"] == str(staged.directory)
    assert found["helper_pid"] == HELPER_PID


def test_a_reopen_request_that_cannot_be_written_never_raises(tmp_path):
    assert install_marker.request_reopen(str(tmp_path / "missing" / "dir"), 1) is False


# ---------------------------------------------------------------------------
# The staged record
# ---------------------------------------------------------------------------


def test_the_record_keeps_counters_for_the_same_version_only(tmp_path):
    dmg = tmp_path / "Mixar-3.4.0.dmg"
    dmg.write_bytes(b"x")
    _record(tmp_path, dmg)
    staged_record.bump(str(tmp_path), "failures", "3.4.0")
    staged_record.bump(str(tmp_path), "launch_attempts", "3.4.0")

    _record(tmp_path, dmg)  # re-verified at the next launch's update check
    record = staged_record.read(str(tmp_path))
    assert (record["failures"], record["launch_attempts"]) == (1, 1)
    assert record["sha256"] == "a" * 64 and record["signer"] == "TEAM123"
    assert record["target"] == "/Applications/Mixar.app"

    other = tmp_path / "Mixar-3.5.0.dmg"
    other.write_bytes(b"y")
    staged_record.write_ready(
        str(tmp_path), version="3.5.0", installer_path=str(other), installer_type="dmg",
        download_url="u", sha256="b", verified=False, signer="IGNORED")
    record = staged_record.read(str(tmp_path))
    assert (record["failures"], record["launch_attempts"]) == (0, 0)
    assert record["signer"] == ""  # only a verified signer is pinned
    assert staged_record.bump(str(tmp_path), "failures", "3.4.0") == 0  # another version


def test_intact_means_the_verified_file(tmp_path):
    dmg = tmp_path / "Mixar-3.4.0.dmg"
    dmg.write_bytes(b"x")
    _record(tmp_path, dmg)
    record = staged_record.read(str(tmp_path))
    assert staged_record.intact(record)

    os.utime(dmg, ns=(1, 1))
    assert not staged_record.intact(record)
    assert not staged_record.intact({"installer": str(tmp_path / "gone")})
    assert not staged_record.intact(None)


def test_a_record_that_cannot_be_read_is_none(tmp_path):
    (tmp_path / STAGED_RECORD_NAME).write_text("{not json")
    assert staged_record.read(str(tmp_path)) is None
    assert staged_record.bump(str(tmp_path), "failures") == 0
    assert staged_record.write_ready(
        str(tmp_path), version="1", installer_path=str(tmp_path / "gone"),
        installer_type="dmg", download_url="", sha256="", verified=False, signer="") is False


def test_the_shared_start_path_owns_marker_connector_and_reopen(tmp_path, monkeypatch):
    """start_helper: reopen requests cleared, marker written, the connector
    marked only when the helper reopens Mixar; stop_helper undoes it."""
    from mixar.modules.mcp_bridge.core import installation as connector_installation

    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    proc = MagicMock(pid=HELPER_PID)
    proc.poll.return_value = None
    monkeypatch.setattr(installer, "begin_install", MagicMock(return_value=proc))
    (tmp_path / HELPER_REOPEN_NAME).write_text("1\n")
    path = str(tmp_path / "Mixar-3.4.0.dmg")

    install_start.start_helper(installer_path=path, version="3.4.0", eligibility=None,
                               verified=False, signer="", trigger="launch", relaunch=True)
    assert connector_installation.updating()
    assert not (tmp_path / HELPER_REOPEN_NAME).exists()
    assert (tmp_path / HELPER_MARKER_NAME).exists()

    install_start.stop_helper(proc, path)
    proc.kill.assert_called_once()
    assert not connector_installation.updating()
    assert not (tmp_path / HELPER_MARKER_NAME).exists()
