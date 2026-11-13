# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared set-up for the install-at-launch tests (issue 2079): a crashed
session left 3.4.0 staged in a throwaway staging directory, 3.3.6 is
starting, every gate is open and the helper, timers and the launch's
signature check are faked."""

import json
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
    LAUNCH_INSTALL_QUIT_DELAY_S,
    STAGED_RECORD_NAME,
    UPDATE_NOTIFICATION_ID,
)
from mixar.modules.common.updates.core import (
    app_paths,
    install_gate,
    installer,
    launch_install,
    staged_record,
    staging,
    trigger,
    update_checker,
    verify,
)

HELPER_PID = 4242
# This launch's own update check: the backend still offers the staged 3.4.0
# installer.
OFFERS_STAGED = {"update_available": True, "latest_version": "3.4.0", "download": {
    "url": "https://cdn.example.com/Mixar-3.4.0.dmg", "sha256": "A" * 64,
    "installer_type": "dmg"}}
CHECK_DELAY_S = 5


class FakeTimers:
    def __init__(self):
        self.registered = {}

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registered[fn] = first_interval

    def unregister(self, fn):
        self.registered.pop(fn, None)

    def is_registered(self, fn):
        return fn in self.registered


def _record(directory, installer_path, **overrides):
    staged_record.write_ready(
        str(directory), version="3.4.0", installer_path=str(installer_path),
        installer_type="dmg", download_url="https://cdn.example.com/Mixar-3.4.0.dmg",
        sha256="A" * 64, verified=True, signer="TEAM123", target="/Applications/Mixar.app")
    if overrides:
        record = staged_record.read(str(directory))
        record.update(overrides)
        (Path(directory) / STAGED_RECORD_NAME).write_text(json.dumps(record))


@pytest.fixture(name="staged")
def staged_fixture(monkeypatch, tmp_path):
    """A crashed session left 3.4.0 staged; 3.3.6 is starting."""
    directory = tmp_path / "Mixar" / "Updates"
    directory.mkdir(parents=True)
    dmg = directory / "Mixar-3.4.0.dmg"
    dmg.write_bytes(b"dmg")
    _record(directory, dmg)

    monkeypatch.setattr(staging, "_is_windows", lambda: False)
    monkeypatch.setattr(staging, "_posix_candidates", lambda: [(str(tmp_path), True)])
    timers = FakeTimers()
    data = SimpleNamespace(filepath="", is_dirty=False,
                           scenes=[SimpleNamespace(name="Scene", mixie_chat_input="")])
    window = SimpleNamespace(modal_operators=[])
    fake_bpy = SimpleNamespace(
        app=SimpleNamespace(background=False, timers=timers,
                            binary_path="/Applications/Mixar.app/Contents/MacOS/Mixar"),
        context=SimpleNamespace(window_manager=SimpleNamespace(windows=[window])),
        data=data, ops=MagicMock())
    monkeypatch.setattr(launch_install, "bpy", fake_bpy)
    monkeypatch.setattr(launch_install, "_asked", {"done": False})
    monkeypatch.setattr(launch_install, "install_on_quit_enabled", lambda: True)
    monkeypatch.setattr(launch_install, "_recovery_offer_pending", lambda: False)
    monkeypatch.setattr(launch_install, "_opened_with_file", lambda: False)
    # Session recovery's and the job queue's busy detectors: an idle
    # session (the bpy mock would read as a running job).
    from mixar.modules.common.job_queue.core import queue_manager
    from mixar.modules.session_recovery import runtime as recovery

    monkeypatch.setattr(recovery, "_busy", lambda: False)
    monkeypatch.setattr(recovery, "agent_scenes", lambda: [])
    monkeypatch.setattr(queue_manager, "active_queue_activity",
                        lambda: queue_manager.QueueActivity(0, "", 0.0))
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    # The installed copy the record names is the one starting.
    monkeypatch.setattr(app_paths, "running_target", lambda: "/Applications/Mixar.app")
    location = app_paths.InstallLocation(
        "/Applications/Mixar.app", True, needs_elevation=False)
    seen_info = []

    def eligibility(info):
        seen_info.append(info)
        return installer.Eligibility(True, location=location, extension=".dmg")

    monkeypatch.setattr(installer, "check_eligibility", eligibility)
    monkeypatch.setattr(install_gate, "silent_blocker", lambda e: "")
    proc = MagicMock(pid=HELPER_PID)
    proc.poll.return_value = None
    begin = MagicMock(return_value=proc)
    monkeypatch.setattr(installer, "begin_install", begin)
    import mixar.modules.common.analytics.update_events as update_events
    monkeypatch.setattr(update_events, "capture_update_started", MagicMock())
    from mixar.modules.mcp_bridge.core import installation as connector_installation
    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    # The launch's own signature check: inline instead of a thread.
    verdict = [(verify.VERIFIED, "TEAM123", "TEAM123")]
    checked = []

    def verify_installer(path, bundle_path="", running_binary=""):
        checked.append((path, bundle_path))
        return verdict[0]

    monkeypatch.setattr(verify, "verify_installer", verify_installer)
    monkeypatch.setattr(launch_install, "_in_background", lambda fn, *args: fn(*args))
    # The update check answers inline with offer[0]: a response body, an
    # exception (the check failed) or None (no answer yet).
    offer = [OFFERS_STAGED]
    asked = []

    def request_update_check(on_success, on_error):
        asked.append((on_success, on_error))
        if isinstance(offer[0], Exception):
            on_error(offer[0])
        elif offer[0] is not None:
            on_success(SimpleNamespace(data=offer[0]))

    monkeypatch.setattr(trigger, "request_update_check", request_update_check)
    get_notification_store().clear_all()
    yield SimpleNamespace(directory=directory, dmg=dmg, timers=timers, data=data, window=window,
                          bpy=fake_bpy, begin=begin, proc=proc, location=location,
                          info=seen_info, verdict=verdict, checked=checked,
                          offer=offer, asked=asked)
    connector_installation.clear_updating()
    get_notification_store().clear_all()


@pytest.fixture(name="this_copy")
def this_copy_fixture(staged, monkeypatch):
    monkeypatch.setattr(app_paths, "running_target", lambda: "/Applications/Mixar.app")
    return staged


def _begin(staged):
    resume = MagicMock()
    launch_install.begin_launch_install(launch_install.launch_install_request(), resume,
                                        check_delay=CHECK_DELAY_S)
    assert staged.timers.registered == {launch_install._check_offer: CHECK_DELAY_S,
                                        launch_install._await_verdict: launch_install._VERIFY_POLL_S}
    # Verified, but this launch's update check has not answered yet.
    assert launch_install._await_verdict() == launch_install._VERIFY_POLL_S
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)
    assert launch_install._check_offer() is None
    assert len(staged.asked) == 1
    assert launch_install._await_verdict() is None  # verified and still offered: announced
    assert staged.checked == [(str(staged.dmg), "/Applications/Mixar.app")]
    toast = next(item for item in get_notification_store().get_visible()
                 if item.id == UPDATE_NOTIFICATION_ID)
    assert toast.title == "Mixar is finishing an update"
    assert staged.timers.registered[launch_install._install] == LAUNCH_INSTALL_QUIT_DELAY_S
    return resume
