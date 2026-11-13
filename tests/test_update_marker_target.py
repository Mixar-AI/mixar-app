# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The update-in-progress marker names the copy its helper installs, and
only a launch of that copy is turned away (issue 2079 review). The staging
directory is per user, so a second copy — a build beside the installed
app, a QA copy — must start while the installed app's helper works.
"""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()
sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

import pytest

from mixar.bootstrap import update_checker as boot
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import HELPER_MARKER_NAME, HELPER_REOPEN_NAME
from mixar.modules.common.updates.core import (
    app_paths,
    install_marker,
    install_start,
    installer,
    launch_install,
    staging,
    update_checker,
)
from mixar.modules.mcp_bridge.core import installation as connector_installation

HELPER_PID = 4242
INSTALLED = "/Applications/Mixar.app"


class FakeTimers:
    def __init__(self):
        self.registered = {}

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registered[fn] = first_interval

    def is_registered(self, fn):
        return fn in self.registered


@pytest.fixture
def stage(monkeypatch, tmp_path):
    """One staging directory; the helper at HELPER_PID is alive."""
    directory = tmp_path / "Mixar" / "Updates"
    directory.mkdir(parents=True)
    monkeypatch.setattr(staging, "_is_windows", lambda: False)
    monkeypatch.setattr(staging, "_posix_candidates", lambda: [(str(tmp_path), True)])
    monkeypatch.setattr(install_marker, "process_identity",
                        lambda pid: (int(pid) == HELPER_PID, None))
    return directory


def _plant(directory, **overrides):
    record = {"helper_pid": HELPER_PID, "helper_created": None, "target_version": "3.4.0",
              "attempt_id": "a1", "target": INSTALLED, "written_at": time.time()}
    record.update(overrides)
    (directory / HELPER_MARKER_NAME).write_text(json.dumps(record))


def test_the_marker_names_the_copy_the_helper_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    proc = MagicMock(pid=HELPER_PID)
    monkeypatch.setattr(installer, "begin_install", MagicMock(return_value=proc))
    location = app_paths.InstallLocation(INSTALLED, True, needs_elevation=False)

    install_start.start_helper(
        installer_path=str(tmp_path / "Mixar-3.4.0.dmg"), version="3.4.0",
        eligibility=installer.Eligibility(True, location=location), verified=True,
        signer="TEAM123", trigger="quit", relaunch=False)

    assert json.loads((tmp_path / HELPER_MARKER_NAME).read_text())["target"] == INSTALLED


@pytest.mark.parametrize("running, turned_away", [
    (INSTALLED, True),
    ("/applications/mixar.APP" if sys.platform == "darwin" else INSTALLED, True),
    (INSTALLED + "/", True),
    ("", True),  # cannot tell (translocated): the safe side
    ("/Users/u/build/Mixar.app", False),
    ("/Applications/Mixar QA.app", False),
])
def test_only_a_launch_of_that_copy_is_turned_away(stage, running, turned_away):
    _plant(stage)

    found = install_marker.check_startup("3.3.6", running)

    assert (found is not None) is turned_away
    assert (stage / HELPER_MARKER_NAME).exists()  # another copy never deletes it


def test_a_marker_from_before_the_target_turns_every_launch_away(stage):
    _plant(stage, target="")
    assert install_marker.check_startup("3.3.6", "/Users/u/build/Mixar.app") is not None
    record = json.loads((stage / HELPER_MARKER_NAME).read_text())
    del record["target"]
    (stage / HELPER_MARKER_NAME).write_text(json.dumps(record))
    assert install_marker.check_startup("3.3.6", "/Users/u/build/Mixar.app") is not None


@pytest.fixture
def boot_env(monkeypatch, stage):
    timers = FakeTimers()
    app = SimpleNamespace(timers=timers, handlers=SimpleNamespace(exit_pre=[]))
    monkeypatch.setattr(boot, "bpy", SimpleNamespace(app=app, ops=MagicMock()))
    monkeypatch.setattr(launch_install, "launch_install_request", lambda: None)
    monkeypatch.setattr(boot, "_init_timer_registered", False)
    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    import mixar.modules.common.analytics.update_events as update_events
    monkeypatch.setattr(update_events, "capture_update_blocked", MagicMock())
    get_notification_store().clear_all()
    yield SimpleNamespace(stage=stage, timers=timers)
    get_notification_store().clear_all()


def test_another_copy_starts_while_the_installed_app_s_helper_works(boot_env, monkeypatch):
    _plant(boot_env.stage)
    monkeypatch.setattr(app_paths, "running_target", lambda: "/Users/u/build/Mixar.app")

    boot.register()

    assert boot._announce_and_quit not in boot_env.timers.registered
    assert boot._delayed_init in boot_env.timers.registered
    assert not (boot_env.stage / HELPER_REOPEN_NAME).exists()  # nothing to reopen


def test_a_launch_of_the_copy_being_installed_is_still_turned_away(boot_env, monkeypatch):
    _plant(boot_env.stage)
    monkeypatch.setattr(app_paths, "running_target", lambda: INSTALLED)

    boot.register()

    assert boot_env.timers.registered == {boot._announce_and_quit: 0.0}
    assert (boot_env.stage / HELPER_REOPEN_NAME).exists()
