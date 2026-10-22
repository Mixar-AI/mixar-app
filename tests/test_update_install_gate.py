# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restart & Update's Windows pre-quit gate, driven through apply_and_restart.

Canned process tables stand in for the native one: a Mixar connector (live
or abandoned) is ended and the update goes ahead, a program the user must
close stops it with the close-apps toast, and Mixar's own background work
is waited for by one timer that continues the update once the table is
clear — or stops on Cancel, on a state change, or when something the user
must close appears. The connector's "updating" marker is written when the
quit is scheduled and cleared when it is aborted.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

import pytest

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import (
    BACKGROUND_POLL_S,
    BACKGROUND_WAIT_MAX_S,
    UPDATE_NOTIFICATION_ID,
    InstallState,
)
from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    install_gate,
    installer,
    toasts,
    win_processes,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state

INSTALL_DIR = r"C:\Program Files\Mixar"
MIXAR = INSTALL_DIR + r"\mixar.exe"
PYTHON = INSTALL_DIR + r"\5.2\python\bin\python.exe"
OWN = os.getpid()
SIGNER = "AB" * 20


class FakeTimers:
    """bpy.app.timers, recording instead of running."""

    def __init__(self):
        self.registered = {}
        self.registrations = []
        self.persistent = {}

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registrations.append(fn)
        self.registered[fn] = first_interval
        self.persistent[fn] = persistent

    def unregister(self, fn):
        if fn not in self.registered:
            raise ValueError("not registered")
        del self.registered[fn]

    def is_registered(self, fn):
        return fn in self.registered


def _row(pid, ppid, name, path, created, window=False):
    return {"pid": pid, "ppid": ppid, "name": name, "path": path,
            "created": created, "has_window": window}


BACKFILL = _row(901, OWN, "mixar.exe", MIXAR, created=20)        # our own work
ORPHAN_CONNECTOR = _row(902, 99999, "python.exe", PYTHON, created=30)
OTHER_WINDOW = _row(903, 1, "mixar.exe", MIXAR, created=5, window=True)
# Claude Code -> cmd.exe (the launcher script) -> the connector's python.
CLAUDE_CONNECTOR = [
    _row(300, 1, "Claude.exe", r"C:\Users\u\Claude\Claude.exe", created=3),
    _row(301, 300, "cmd.exe", r"C:\Windows\System32\cmd.exe", created=4),
    _row(302, 301, "python.exe", PYTHON, created=4),
]


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    timers = FakeTimers()
    fake_bpy = SimpleNamespace(
        app=SimpleNamespace(timers=timers, binary_path=""),
        data=SimpleNamespace(is_dirty=False), ops=MagicMock(), context=MagicMock(),
    )
    monkeypatch.setattr(install_gate, "bpy", fake_bpy)
    monkeypatch.setattr(install_flow, "bpy", fake_bpy)
    monkeypatch.setattr(install_gate, "_is_windows", lambda: True)
    table = [_row(OWN, 1, "mixar.exe", MIXAR, created=10, window=True)]
    monkeypatch.setattr(win_processes, "_process_table", lambda: list(table))
    terminate = MagicMock(return_value=True)
    monkeypatch.setattr(win_processes, "terminate", terminate)
    location = app_paths.InstallLocation(INSTALL_DIR, True, "", kind="msi")
    monkeypatch.setattr(installer, "check_eligibility", lambda info: installer.Eligibility(
        True, location=location, extension=".msi"))
    began = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(installer, "begin_install", began)
    import mixar.modules.common.updates.core.update_checker as update_checker
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")

    installer_file = tmp_path / "Mixar-3.4.0.msi"
    installer_file.write_bytes(b"msi")
    state = get_update_state()
    state.set_idle()
    state.set_available(UpdateInfo(
        latest_version="3.4.0", current_version="3.3.6",
        download_url="https://cdn.example.com/Mixar-3.4.0.msi",
        download_sha256="a" * 64, installer_type="msi",
    ))
    state.set_ready(str(installer_file), True, SIGNER)
    get_notification_store().clear_all()
    install_gate._stop()
    yield SimpleNamespace(table=table, timers=timers, bpy=fake_bpy,
                          terminate=terminate, began=began, state=state)
    install_gate._stop()
    install_flow._helper_proc = None
    state.set_idle()
    get_notification_store().clear_all()


def _toast():
    return next(item for item in get_notification_store().get_visible()
                if item.id == UPDATE_NOTIFICATION_ID)


def _start_waiting(gate):
    gate.table.append(BACKFILL)
    assert install_flow.apply_and_restart() == (False, install_flow.WAITING_FOR_BACKGROUND)


def test_abandoned_connectors_are_ended_and_the_update_proceeds(gate):
    gate.table.append(ORPHAN_CONNECTOR)

    assert install_flow.apply_and_restart() == (True, "")

    (ended,), _ = gate.terminate.call_args
    assert (ended.kind, ended.name, ended.pid, ended.created) == (
        win_processes.ABANDONED_CONNECTOR, "python.exe", 902, 30)
    gate.began.assert_called_once()
    assert gate.began.call_args.kwargs["signer_thumbprint"] == SIGNER
    assert gate.state.install_state is InstallState.INSTALLING


def test_an_abandoned_connector_that_survives_is_named(gate):
    gate.table.append(ORPHAN_CONNECTOR)
    gate.terminate.return_value = False

    assert install_flow.apply_and_restart() == (False, install_flow.BLOCKED_BY_OTHER_APPS)

    assert "python.exe" in _toast().body
    gate.began.assert_not_called()


def test_a_live_connector_is_ended_and_the_update_proceeds(gate):
    """An AI app's MCP server holds no user work and is stale once Mixar
    restarts: the user is not asked to close Claude or Codex."""
    gate.table += CLAUDE_CONNECTOR

    assert install_flow.apply_and_restart() == (True, "")

    (ended,), _ = gate.terminate.call_args
    assert (ended.kind, ended.name, ended.pid, ended.created) == (
        win_processes.CONNECTOR, "Claude", 302, 4)
    gate.began.assert_called_once()
    assert gate.state.install_state is InstallState.INSTALLING


def test_a_live_connector_that_survives_is_named_after_its_app(gate):
    gate.table += CLAUDE_CONNECTOR
    gate.terminate.return_value = False

    assert install_flow.apply_and_restart() == (False, install_flow.BLOCKED_BY_OTHER_APPS)

    assert "Claude (using the Mixar connector)" in _toast().body
    gate.began.assert_not_called()


def test_programs_the_user_must_close_stop_the_update(gate):
    gate.table += CLAUDE_CONNECTOR + [OTHER_WINDOW, BACKFILL]

    assert install_flow.apply_and_restart() == (False, install_flow.BLOCKED_BY_OTHER_APPS)

    item = _toast()
    assert item.title == "Close other apps to update"
    assert "Another Mixar window" in item.body
    assert "Claude" not in item.body  # never the user's to close
    gate.terminate.assert_not_called()  # ended only once the update goes ahead
    assert "mixar.exe" not in item.body  # our own work is not the user's to close
    assert install_gate._poll not in gate.timers.registered
    gate.began.assert_not_called()
    assert gate.state.install_state is InstallState.READY


def test_a_connector_is_left_alone_until_the_background_wait_clears(gate):
    """The AI app keeps working through its connector while Mixar's own
    work finishes: the poll must not kill it every BACKGROUND_POLL_S."""
    gate.table += CLAUDE_CONNECTOR + [BACKFILL]
    # An ended process leaves the table (the check runs again before the quit).
    gate.terminate.side_effect = lambda holder: gate.table.remove(
        next(row for row in gate.table if row["pid"] == holder.pid)) or True

    assert install_flow.apply_and_restart() == (False, install_flow.WAITING_FOR_BACKGROUND)
    assert install_gate._poll() == BACKGROUND_POLL_S
    gate.terminate.assert_not_called()

    gate.table.remove(BACKFILL)
    assert install_gate._poll() is None

    gate.terminate.assert_called_once()
    assert gate.terminate.call_args[0][0].pid == 302
    gate.began.assert_called_once()
    assert gate.state.install_state is InstallState.INSTALLING


def test_the_quit_marks_the_connector_updating_and_an_abort_clears_it(gate, monkeypatch):
    """A connector an AI app starts while Mixar is gone must wait for the
    helper's relaunch instead of cold-starting the old binary."""
    from mixar.modules.mcp_bridge.core import installation

    popen = MagicMock()
    monkeypatch.setattr(installation.subprocess, "Popen", popen)
    assert not installation.updating()

    assert install_flow.apply_and_restart() == (True, "")

    assert installation.updating()
    assert installation.start_in_progress()
    assert installation.start_app() is False
    popen.assert_not_called()

    install_flow._abort_pending_install()

    assert not installation.updating()
    assert not installation.start_in_progress()


def test_background_work_is_waited_for_and_the_update_continues(gate):
    _start_waiting(gate)

    item = _toast()
    assert item.title == "Finishing background work"
    assert [(a.label, a.operator) for a in item.actions] == [
        ("Cancel", "mixar.cancel_update_wait")]
    assert item.dismissible is False
    assert gate.timers.registered == {install_gate._poll: BACKGROUND_POLL_S}
    gate.began.assert_not_called()
    assert gate.state.install_state is InstallState.READY

    assert install_gate._poll() == BACKGROUND_POLL_S  # still running
    gate.table.remove(BACKFILL)
    assert install_gate._poll() is None

    gate.began.assert_called_once()
    assert gate.state.install_state is InstallState.INSTALLING
    assert not install_gate.is_waiting()


def test_the_poll_is_registered_once(gate):
    _start_waiting(gate)
    assert install_flow.apply_and_restart() == (False, install_flow.WAITING_FOR_BACKGROUND)
    assert install_gate._poll() == BACKGROUND_POLL_S

    assert gate.timers.registrations.count(install_gate._poll) == 1


def test_the_poll_survives_opening_a_file(gate):
    # A non-persistent timer is dropped on file load, leaving the wait toast
    # up with nothing polling.
    _start_waiting(gate)

    assert gate.timers.persistent[install_gate._poll] is True


def test_cancel_stops_the_poll_and_keeps_the_update_ready(gate):
    _start_waiting(gate)

    install_gate.cancel_wait()

    assert install_gate._poll not in gate.timers.registered
    assert install_gate._poll() is None
    item = _toast()
    assert item.title == "Mixar Update Ready"
    assert [a.label for a in item.actions] == ["Restart & Update"]
    assert gate.state.install_state is InstallState.READY
    gate.began.assert_not_called()


def test_the_poll_stops_when_the_update_is_no_longer_ready(gate):
    _start_waiting(gate)
    gate.state.set_install_failed("Download failed")

    assert install_gate._poll() is None
    assert not install_gate.is_waiting()
    gate.began.assert_not_called()


def test_a_program_to_close_appearing_mid_wait_ends_the_wait(gate):
    _start_waiting(gate)
    gate.table.append(OTHER_WINDOW)

    assert install_gate._poll() is None
    assert _toast().title == "Close other apps to update"
    assert not install_gate.is_waiting()
    gate.began.assert_not_called()


def test_unsaved_edits_go_through_the_restart_prompt(gate, monkeypatch):
    _start_waiting(gate)
    gate.table.remove(BACKFILL)
    gate.bpy.data.is_dirty = True
    prompt = MagicMock()
    monkeypatch.setattr(install_flow, "open_restart_prompt", prompt)

    assert install_gate._poll() is None

    prompt.assert_called_once_with()
    gate.began.assert_not_called()


def test_a_wait_past_the_limit_hands_over_to_the_helper(gate, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(install_gate, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    _start_waiting(gate)
    clock[0] += BACKGROUND_WAIT_MAX_S

    assert install_gate._poll() is None

    gate.began.assert_called_once()
    assert not install_gate.is_waiting()


def test_the_update_toast_keeps_showing_the_wait(gate):
    """The badge's "show toast" must not swap the wait for Restart & Update."""
    _start_waiting(gate)

    toasts.push_update_available_toast(gate.state.update_info)

    assert _toast().title == "Finishing background work"


def test_operator_keeps_the_waiting_toast_and_registers_cancel():
    source = (SCRIPTS / "mixar" / "modules" / "common" / "updates" / "ui"
              / "operators.py").read_text(encoding="utf-8")
    block = source[source.index("started, message = apply_and_restart()"):]
    assert block.index("WAITING_FOR_BACKGROUND") < block.index("refresh_update_toast()")
    assert 'bl_idname = "mixar.cancel_update_wait"' in source
    assert "    MIXAR_OT_cancel_update_wait,\n" in source[source.index("classes = ("):]
