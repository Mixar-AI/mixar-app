# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install on quit (issue 2079): a staged, verified, eligible update is
installed when the user quits Mixar normally, without a prompt or a wait.

Pinned here: the ``exit_pre`` hook and its boolean, every reason it stands
down (an abnormal exit, Restart & Update's own quit, the setting, an
administrator prompt, another Mixar or background work, earlier failures),
the shared start path with Restart & Update, the helper's no-relaunch
mode, and the ``trigger`` telemetry.
"""

import ast
import inspect
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

from mixar.bootstrap import update_checker as boot
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import (
    HELPER_MARKER_NAME,
    HELPER_REOPEN_NAME,
    SILENT_INSTALL_MAX_FAILURES,
    InstallState,
)
from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    install_gate,
    install_start,
    installer,
    silent_install,
    staged_record,
    staging,
    update_checker,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.mcp_bridge.core import installation as connector_installation

CORE = SCRIPTS / "mixar" / "modules" / "common" / "updates" / "core"


def _info(version="3.4.0"):
    return UpdateInfo(
        latest_version=version, current_version="3.3.6",
        download_url=f"https://cdn.example.com/Mixar-{version}.dmg",
        download_sha256="a" * 64, download_size=3, installer_type="dmg",
    )


class FakeTimers:
    def __init__(self):
        self.registered = {}

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registered[fn] = first_interval

    def unregister(self, fn):
        self.registered.pop(fn, None)

    def is_registered(self, fn):
        return fn in self.registered


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """A verified update staged in *tmp_path*, every gate open, helper faked."""
    directory = tmp_path / "Updates"
    directory.mkdir()
    path = directory / "Mixar-3.4.0.dmg"
    path.write_bytes(b"dmg")
    location = app_paths.InstallLocation(
        "/Applications/Mixar.app", True, relaunch_candidates=["/Applications/Mixar.app"],
        needs_elevation=False)
    monkeypatch.setattr(installer, "check_eligibility",
                        lambda info: installer.Eligibility(True, location=location, extension=".dmg"))
    monkeypatch.setattr(install_gate, "silent_blocker", lambda eligibility: "")
    monkeypatch.setattr(silent_install, "install_on_quit_enabled", lambda: True)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    connector_installation.clear_updating()
    proc = MagicMock(pid=4242)
    proc.poll.return_value = None
    begin = MagicMock(return_value=proc)
    monkeypatch.setattr(installer, "begin_install", begin)
    started = MagicMock()
    import mixar.modules.common.analytics.update_events as update_events
    monkeypatch.setattr(update_events, "capture_update_started", started)

    state = get_update_state()
    state.set_idle()
    state.set_available(_info())
    staged_record.write_ready(
        str(directory), version="3.4.0", installer_path=str(path), installer_type="dmg",
        download_url=_info().download_url, sha256="a" * 64, verified=True, signer="TEAM123")
    state.set_ready(str(path), True, "TEAM123")
    yield SimpleNamespace(directory=directory, path=path, begin=begin, proc=proc,
                          started=started, location=location)
    get_update_state().set_idle()
    connector_installation.clear_updating()


# ---------------------------------------------------------------------------
# The quit installs
# ---------------------------------------------------------------------------


def test_a_normal_quit_starts_the_helper_without_a_relaunch(ready):
    assert silent_install.install_on_quit(True) is True

    kwargs = ready.begin.call_args.kwargs
    assert kwargs["relaunch"] is False and kwargs["trigger"] == "quit"
    assert kwargs["installer_path"] == str(ready.path)
    assert kwargs["verified"] is True and kwargs["signer_thumbprint"] == "TEAM123"
    assert kwargs["from_version"] == "3.3.6" and kwargs["attempt_id"]
    # The marker turns a Mixar opened meanwhile away, as for Restart & Update.
    record = json.loads((ready.directory / HELPER_MARKER_NAME).read_text())
    assert record["helper_pid"] == 4242 and record["attempt_id"] == kwargs["attempt_id"]
    # Nothing would clear the connector's "updating" mark for 15 minutes.
    assert not connector_installation.updating()
    assert get_update_state().install_state is InstallState.INSTALLING
    ready.started.assert_called_once_with(
        "3.4.0", True, attempt_id=kwargs["attempt_id"], trigger="quit")


def test_the_quit_shows_nothing_and_schedules_nothing(ready, monkeypatch):
    timers = FakeTimers()
    monkeypatch.setattr(install_flow, "bpy", SimpleNamespace(app=SimpleNamespace(timers=timers)))
    get_notification_store().clear_all()

    silent_install.install_on_quit(True)

    assert timers.registered == {}
    assert get_notification_store().get_visible() == []


@pytest.mark.parametrize("user_exit", [False, None, 0, "True"])
def test_only_a_normal_quit_installs(ready, user_exit):
    """False: background mode, a failed start, sys.exit (Blender's own
    distinction). Anything that is not exactly True is not a user quit."""
    assert silent_install.install_on_quit(user_exit) is False
    ready.begin.assert_not_called()


def test_restart_and_update_s_own_quit_is_not_a_second_install(ready):
    get_update_state().set_installing()

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


@pytest.mark.parametrize("install_state", ["idle", "downloading", "failed"])
def test_nothing_staged_nothing_installed(ready, install_state):
    state = get_update_state()
    {"idle": state.set_install_idle, "downloading": state.set_downloading,
     "failed": lambda: state.set_install_failed("x")}[install_state]()

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


def test_the_setting_turns_it_off(ready, monkeypatch):
    monkeypatch.setattr(silent_install, "install_on_quit_enabled", lambda: False)

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()
    assert get_update_state().install_state is InstallState.READY


def test_an_install_that_needs_the_admin_prompt_waits_for_the_click(ready):
    ready.location.needs_elevation = True

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


def test_another_mixar_or_background_work_stops_it(ready, monkeypatch):
    monkeypatch.setattr(install_gate, "silent_blocker", lambda eligibility: "Mixar")

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


@pytest.mark.parametrize("verified, signer", [(False, ""), (True, "")])
def test_an_update_not_pinned_to_this_app_s_team_waits_for_the_click(ready, verified, signer):
    """An unsigned or dev build (no Team ID to pin) keeps Restart to Update."""
    get_update_state().set_ready(str(ready.path), verified, signer)
    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


def test_a_version_that_kept_failing_stops_installing_by_itself(ready):
    for _ in range(SILENT_INSTALL_MAX_FAILURES):
        staged_record.bump(str(ready.directory), "failures", "3.4.0")

    assert silent_install.install_on_quit(True) is False
    ready.begin.assert_not_called()


def test_a_missing_installer_is_not_installed(ready):
    ready.path.unlink()

    assert silent_install.install_on_quit(True) is False


def test_a_helper_that_cannot_start_leaves_the_quit_alone(ready):
    ready.begin.side_effect = OSError("read-only")

    assert silent_install.install_on_quit(True) is False
    assert not (ready.directory / HELPER_MARKER_NAME).exists()
    assert get_update_state().install_state is InstallState.READY


def test_stale_reopen_requests_are_forgotten_before_the_helper_starts(ready):
    (ready.directory / HELPER_REOPEN_NAME).write_text("999\n")

    silent_install.install_on_quit(True)

    assert not (ready.directory / HELPER_REOPEN_NAME).exists()


# ---------------------------------------------------------------------------
# One preparation path
# ---------------------------------------------------------------------------


def _calls(function):
    tree = ast.parse(inspect.getsource(function))
    return {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}


def test_restart_and_update_and_the_quit_share_one_start_path():
    assert "install_start.start_helper" in _calls(install_flow.apply_and_restart)
    assert "install_start.start_helper" in _calls(silent_install._install_on_quit)
    # Neither spawns, marks or reports on its own any more.
    for function in (install_flow.apply_and_restart, silent_install._install_on_quit):
        calls = _calls(function)
        assert "installer.begin_install" not in calls
        assert not any("install_marker" in call or "capture_update_started" in call
                       for call in calls)
    assert "install_start.stop_helper" in _calls(install_flow._abort_pending_install)


def test_restart_and_update_still_relaunches_and_says_click(ready, monkeypatch):
    timers = FakeTimers()
    monkeypatch.setattr(install_flow, "bpy", SimpleNamespace(
        app=SimpleNamespace(timers=timers), ops=MagicMock()))
    monkeypatch.setattr(install_flow.install_gate, "check", lambda eligibility: "")

    assert install_flow.apply_and_restart() == (True, "")

    kwargs = ready.begin.call_args.kwargs
    assert kwargs["relaunch"] is True and kwargs["trigger"] == "click"
    assert connector_installation.updating()  # the relaunched app's relay clears it
    assert ready.started.call_args.kwargs["trigger"] == "click"
    assert install_flow._quit in timers.registered


# ---------------------------------------------------------------------------
# The hook
# ---------------------------------------------------------------------------


def test_the_exit_pre_handler_takes_blender_s_boolean():
    """Blender passes exit_pre's argument only to a one-parameter handler."""
    assert boot._on_exit_pre.__code__.co_argcount == 1
    source = inspect.getsource(boot)
    assert "@persistent\ndef _on_exit_pre(user_exit)" in source


def test_the_handler_forwards_the_boolean(monkeypatch):
    seen = []
    monkeypatch.setattr(silent_install, "install_on_quit", seen.append)

    boot._on_exit_pre(True)
    boot._on_exit_pre(False)

    assert seen == [True, False]


@pytest.fixture
def boot_bpy(monkeypatch):
    timers = FakeTimers()
    fake = SimpleNamespace(app=SimpleNamespace(
        timers=timers, handlers=SimpleNamespace(exit_pre=[])))
    monkeypatch.setattr(boot, "bpy", fake)
    monkeypatch.setattr(boot, "_init_timer_registered", False)
    monkeypatch.setattr(boot, "_install_in_progress", lambda: False)
    monkeypatch.setattr(boot, "_launch_install_started", lambda: False)
    return fake


def test_startup_adds_the_handler_once_and_shutdown_removes_it(boot_bpy):
    boot.register()
    boot.register()  # a second register is a no-op

    assert boot_bpy.app.handlers.exit_pre == [boot._on_exit_pre]
    assert boot._delayed_init in boot_bpy.app.timers.registered

    boot.unregister()
    assert boot_bpy.app.handlers.exit_pre == []


def test_a_launch_that_quits_mid_install_adds_no_handler(boot_bpy, monkeypatch):
    monkeypatch.setattr(boot, "_install_in_progress", lambda: True)

    boot.register()

    assert boot_bpy.app.handlers.exit_pre == []


def test_without_handlers_startup_goes_on(monkeypatch):
    timers = FakeTimers()
    monkeypatch.setattr(boot, "bpy", SimpleNamespace(app=SimpleNamespace(timers=timers)))
    monkeypatch.setattr(boot, "_init_timer_registered", False)
    monkeypatch.setattr(boot, "_install_in_progress", lambda: False)
    monkeypatch.setattr(boot, "_launch_install_started", lambda: False)

    boot.register()

    assert list(timers.registered) == [boot._delayed_init]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_needs_elevation_is_the_one_gate(monkeypatch, tmp_path):
    """False for a writable macOS bundle (and a Windows per-user install in
    the profile: tests/test_windows_install_scope.py), True for a Windows
    install in Program Files and by default."""
    assert app_paths.InstallLocation("x", True).needs_elevation is True

    bundle = tmp_path / "Mixar.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    monkeypatch.setattr(app_paths, "_binary_path",
                        lambda: str(bundle / "Contents" / "MacOS" / "Mixar"))
    assert app_paths._macos_location().needs_elevation is False

    monkeypatch.setattr(app_paths, "_binary_path", lambda: r"C:\Program Files\Mixar\mixar.exe")
    monkeypatch.setattr(app_paths, "windows_msi_installs", lambda: [])
    monkeypatch.setattr(app_paths, "classify_windows_install", lambda *a: ("msi", None))
    monkeypatch.setattr(app_paths.os.path, "abspath", lambda p: p)
    monkeypatch.setattr(app_paths.os.path, "dirname", lambda p: r"C:\Program Files\Mixar")
    assert app_paths._windows_location().needs_elevation is True


def test_the_silent_gate_refuses_what_restart_and_update_would_ask_about(ready, monkeypatch):
    eligibility = installer.check_eligibility(_info())
    pinned = {"verified": True, "signer": "TEAM123"}
    assert silent_install.silent_refusal(eligibility, **pinned) == ""
    assert silent_install.silent_refusal(installer.Eligibility(False, "nope"), **pinned) == "nope"
    monkeypatch.setattr(install_gate, "silent_blocker", lambda e: "Mixar, Blender")
    assert "Mixar, Blender" in silent_install.silent_refusal(eligibility, **pinned)


def test_the_silent_blocker_fails_closed(monkeypatch):
    from mixar.modules.common.updates.core import mac_processes

    location = app_paths.InstallLocation("/Applications/Mixar.app", True, needs_elevation=False)
    eligibility = installer.Eligibility(True, location=location)
    monkeypatch.setattr(install_gate, "_is_windows", lambda: False)
    monkeypatch.setattr(install_gate.sys, "platform", "darwin")
    monkeypatch.setattr(mac_processes, "process_table", MagicMock(side_effect=OSError("no")))

    assert install_gate.silent_blocker(eligibility) == "process table unavailable"
    assert install_gate.silent_blocker(installer.Eligibility(True)) != ""


def test_the_silent_blocker_ignores_connectors_on_windows(monkeypatch):
    from mixar.modules.common.updates.core import win_processes

    location = app_paths.InstallLocation(r"C:\Program Files\Mixar", True)
    eligibility = installer.Eligibility(True, location=location)
    holders = [
        win_processes.Holder(win_processes.CONNECTOR, "Claude", 11, None),
        win_processes.Holder(win_processes.ABANDONED_CONNECTOR, "python.exe", 12, None),
    ]
    monkeypatch.setattr(install_gate, "_is_windows", lambda: True)
    monkeypatch.setattr(install_gate, "_silent_holders", lambda target: list(holders))
    assert install_gate.silent_blocker(eligibility) == ""

    holders.append(win_processes.Holder(win_processes.BACKGROUND, "mixar.exe", 13, None))
    assert install_gate.silent_blocker(eligibility) == "mixar.exe"


# ---------------------------------------------------------------------------
# Telemetry and the helper's mode
# ---------------------------------------------------------------------------


def test_begin_install_passes_the_mode_to_the_macos_helper(monkeypatch):
    from mixar.modules.common.updates.core import mac_installer

    launched = MagicMock()
    monkeypatch.setattr(mac_installer, "launch", launched)
    monkeypatch.setattr(installer.os, "name", "posix")
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    location = app_paths.InstallLocation("/Applications/Mixar.app", True, needs_elevation=False)

    installer.begin_install(
        installer_path="/u/Updates/Mixar-3.4.0.dmg", staging_dir="/u/Updates",
        version="3.4.0", eligibility=installer.Eligibility(True, location=location),
        verified=True, signer_thumbprint="TEAM123", from_version="3.3.6",
        attempt_id="ab", relaunch=False, trigger="quit")

    kwargs = launched.call_args.kwargs
    # The Team ID came from the download thread's check: no codesign here.
    assert kwargs["expected_team"] == "TEAM123" and kwargs["require_signature"] is True
    assert kwargs["relaunch"] is False and kwargs["trigger"] == "quit"
    assert kwargs["from_version"] == "3.3.6" and kwargs["attempt_id"] == "ab"


def test_an_unverified_install_pins_no_team(monkeypatch):
    from mixar.modules.common.updates.core import mac_installer

    launched = MagicMock()
    monkeypatch.setattr(mac_installer, "launch", launched)
    monkeypatch.setattr(installer.os, "name", "posix")
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    location = app_paths.InstallLocation("/Applications/Mixar.app", True)

    installer.begin_install(
        installer_path="/u/Mixar.dmg", staging_dir="/u", version="3.4.0",
        eligibility=installer.Eligibility(True, location=location), verified=False,
        signer_thumbprint="STALE")

    assert launched.call_args.kwargs["expected_team"] == ""
    assert launched.call_args.kwargs["relaunch"] is True  # Restart & Update's default


def test_macos_verification_returns_the_team_the_helper_pins(monkeypatch):
    from mixar.modules.common.updates.core import verify

    monkeypatch.setattr(verify, "_run", lambda argv: (0, ""))
    teams = {"/Applications/Mixar.app": "TEAM123", "/u/Mixar.dmg": "TEAM123"}
    monkeypatch.setattr(verify, "team_id", lambda path: teams[str(path)])
    monkeypatch.setattr(verify.os, "name", "posix")
    monkeypatch.setattr(verify.sys, "platform", "darwin")

    verdict, _detail, signer = verify.verify_installer(
        "/u/Mixar.dmg", bundle_path="/Applications/Mixar.app")

    assert verdict == verify.VERIFIED and signer == "TEAM123"


def test_staging_keeps_the_record_through_the_purge(monkeypatch, tmp_path):
    kept = {}
    monkeypatch.setattr(staging, "resolve_staging_dir",
                        lambda: staging.StagingDir(str(tmp_path), True))
    monkeypatch.setattr(staging, "purge_stale",
                        lambda directory, keep_filenames=(): kept.update(names=keep_filenames))

    install_flow._prepare_staging("3.4.0", ".dmg")

    assert "staged-update.json" in kept["names"] and "Mixar-3.4.0.dmg" in kept["names"]
