# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The update-in-progress marker: written after the helper spawns, cleared
by the helper on every exit path, and honoured at startup and by the purge.

A Mixar opened by hand while a helper installs must not run (half-replaced
files, a held install directory) and must not purge the staging directory
(the Windows helper's batch file is read line by line). It says "finishing
an update" and quits — unless the marker is stale or names this very build.
"""

import json
import os
import re
import subprocess
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
    HELPER_MARKER_MAX_AGE_S,
    HELPER_MARKER_NAME,
    HELPER_RESULT_NAME,
    HELPER_WAIT_FOR_EXIT_S,
    HELPER_WAIT_FOR_LOCKS_S,
    MID_INSTALL_QUIT_DELAY_S,
    UPDATE_NOTIFICATION_ID,
    InstallState,
)
from mixar.modules.common.updates.core import (
    install_flow,
    install_marker,
    installer,
    mac_installer,
    staging,
    update_checker,
    win_installer,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.mcp_bridge.core import installation as connector_installation

HELPER_PID = 4242
CREATED = "1792611196.598881"


class FakeTimers:
    def __init__(self):
        self.registered = {}

    def register(self, fn, first_interval=0.0, persistent=False):
        self.registered[fn] = first_interval

    def unregister(self, fn):
        self.registered.pop(fn, None)

    def is_registered(self, fn):
        return fn in self.registered


def _info():
    return UpdateInfo(
        latest_version="3.4.0", current_version="3.3.6",
        download_url="https://cdn.example.com/Mixar-3.4.0.dmg",
        download_sha256="a" * 64, download_size=1, installer_type="dmg",
    )


@pytest.fixture
def stage(monkeypatch, tmp_path):
    """One staging directory; the helper at HELPER_PID is alive with CREATED."""
    directory = tmp_path / "Mixar" / "Updates"
    directory.mkdir(parents=True)
    monkeypatch.setattr(staging, "_is_windows", lambda: False)
    monkeypatch.setattr(staging, "_posix_candidates", lambda: [(str(tmp_path), True)])
    processes = {HELPER_PID: (True, CREATED)}
    monkeypatch.setattr(
        install_marker, "process_identity",
        lambda pid: processes.get(int(pid), (False, None)))
    return SimpleNamespace(path=directory, processes=processes)


def _plant(directory, **overrides):
    record = {"helper_pid": HELPER_PID, "helper_created": CREATED,
              "target_version": "3.4.0", "attempt_id": "a1", "written_at": time.time()}
    record.update(overrides)
    (directory / HELPER_MARKER_NAME).write_text(json.dumps(record), encoding="utf-8")


# ---------------------------------------------------------------------------
# Written after the spawn, removed on abort
# ---------------------------------------------------------------------------


@pytest.fixture
def ready(monkeypatch, stage):
    timers = FakeTimers()
    monkeypatch.setattr(install_flow, "bpy", SimpleNamespace(
        app=SimpleNamespace(timers=timers, binary_path=""), ops=MagicMock()))
    monkeypatch.setattr(installer, "check_eligibility",
                        lambda info: installer.Eligibility(True, extension=".dmg"))
    monkeypatch.setattr(install_flow.install_gate, "check", lambda eligibility: "")
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    path = stage.path / "Mixar-3.4.0.dmg"
    path.write_bytes(b"dmg")
    state = get_update_state()
    state.set_idle()
    state.set_available(_info())
    state.set_ready(str(path), True, "")
    get_notification_store().clear_all()
    yield stage
    get_update_state().set_idle()


def test_marker_is_written_once_the_helper_is_running(monkeypatch, ready):
    proc = MagicMock(pid=HELPER_PID)
    proc.poll.return_value = None
    monkeypatch.setattr(installer, "begin_install", MagicMock(return_value=proc))

    assert install_flow.apply_and_restart() == (True, "")

    record = json.loads((ready.path / HELPER_MARKER_NAME).read_text())
    assert record["helper_pid"] == HELPER_PID and record["helper_created"] == CREATED
    assert record["target_version"] == "3.4.0" and record["attempt_id"]
    assert abs(record["written_at"] - time.time()) < 60
    assert not (ready.path / (HELPER_MARKER_NAME + ".tmp")).exists()


def test_no_marker_when_the_helper_could_not_start(monkeypatch, ready):
    monkeypatch.setattr(installer, "begin_install", MagicMock(side_effect=OSError("no")))

    assert install_flow.apply_and_restart()[0] is False
    assert not (ready.path / HELPER_MARKER_NAME).exists()


def test_a_marker_that_cannot_be_written_never_blocks_the_update(monkeypatch, ready):
    monkeypatch.setattr(installer, "begin_install", MagicMock(return_value=MagicMock(pid=1)))
    monkeypatch.setattr(install_marker.os, "replace", MagicMock(side_effect=OSError("ro")))

    assert install_flow.apply_and_restart() == (True, "")
    assert not list(ready.path.glob(HELPER_MARKER_NAME + "*"))


def test_an_aborted_quit_removes_the_marker(monkeypatch, ready):
    proc = MagicMock(pid=HELPER_PID)
    proc.poll.return_value = None
    monkeypatch.setattr(installer, "begin_install", MagicMock(return_value=proc))
    install_flow.apply_and_restart()

    install_flow._quit_watchdog()

    proc.kill.assert_called_once()
    assert not (ready.path / HELPER_MARKER_NAME).exists()
    assert get_update_state().install_state is InstallState.READY


def _staged_files(directory):
    for name in ("mixar-update-3.4.0.cmd", "mixar-update-3.4.0.sh", "Mixar-3.4.0.msi",
                 "Mixar-3.3.0.dmg"):
        (directory / name).write_bytes(b"x")


# ---------------------------------------------------------------------------
# Startup check (the bootstrap hook)
# ---------------------------------------------------------------------------


@pytest.fixture
def boot_env(monkeypatch, stage):
    timers = FakeTimers()
    fake_bpy = SimpleNamespace(app=SimpleNamespace(timers=timers), ops=MagicMock())
    monkeypatch.setattr(boot, "bpy", fake_bpy)
    monkeypatch.setattr(boot, "_init_timer_registered", False)
    monkeypatch.setattr(connector_installation, "_keep_updating", False)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")
    blocked = MagicMock()
    import mixar.modules.common.analytics.update_events as update_events
    monkeypatch.setattr(update_events, "capture_update_blocked", blocked)
    (stage.path / HELPER_RESULT_NAME).write_text("version=3.3.6\nstage=install\nexit=0\n")
    get_notification_store().clear_all()
    yield SimpleNamespace(stage=stage, timers=timers, bpy=fake_bpy, blocked=blocked)
    get_notification_store().clear_all()


def test_a_live_helper_stops_the_launch(boot_env):
    _plant(boot_env.stage.path)
    connector_installation.mark_updating()  # written by the Mixar that quit

    boot.register()

    # This launch's relay publishes before it quits (mcp_bridge ticks at
    # 3 s, the quit comes at 5 s): that must not end the update's window.
    connector_installation.started()
    assert connector_installation.updating()

    timers = boot_env.timers.registered
    assert boot._delayed_init not in timers  # no result report, no update check
    assert timers == {boot._announce_and_quit: 0.0}
    boot._announce_and_quit()

    toast = next(item for item in get_notification_store().get_visible()
                 if item.id == UPDATE_NOTIFICATION_ID)
    assert toast.title == "Mixar is finishing an update"
    assert toast.body == "It will reopen automatically when it's done."
    assert timers[boot._quit_for_update] == MID_INSTALL_QUIT_DELAY_S
    boot_env.blocked.assert_called_once_with("3.4.0")
    boot._quit_for_update()
    boot_env.bpy.ops.wm.quit_blender.assert_called_once_with()
    # Untouched: the result belongs to the launch after the install.
    assert (boot_env.stage.path / HELPER_RESULT_NAME).exists()
    assert (boot_env.stage.path / HELPER_MARKER_NAME).exists()


def _age(path):
    long_ago = time.time() - HELPER_MARKER_MAX_AGE_S - 1
    os.utime(path, (long_ago, long_ago))


@pytest.mark.parametrize("case", ["dead", "reused", "too_old", "old_corrupt", "old_not_a_dict"])
def test_a_stale_marker_is_deleted_and_the_launch_goes_on(boot_env, case):
    directory = boot_env.stage.path
    if case == "dead":
        _plant(directory, helper_pid=5555)
    elif case == "reused":
        _plant(directory, helper_created="1700000000.000001")
    elif case == "too_old":
        _plant(directory, written_at=time.time() - HELPER_MARKER_MAX_AGE_S - 1)
    elif case == "old_corrupt":
        (directory / HELPER_MARKER_NAME).write_text('{"helper_pid": 42', encoding="utf-8")
        _age(directory / HELPER_MARKER_NAME)
    else:
        (directory / HELPER_MARKER_NAME).write_text("[1, 2]", encoding="utf-8")
        _age(directory / HELPER_MARKER_NAME)

    boot.register()

    assert boot._delayed_init in boot_env.timers.registered
    assert boot._announce_and_quit not in boot_env.timers.registered
    assert not (directory / HELPER_MARKER_NAME).exists()


@pytest.mark.parametrize("case", ["corrupt", "not_a_dict", "lookup_raises"])
def test_a_marker_that_cannot_be_judged_is_kept_and_the_launch_goes_on(
        boot_env, monkeypatch, case):
    """Antivirus holding the new file, or a failing process lookup: the
    helper may well be live, so the file stays (it still guards the
    purge, which would otherwise delete the helper's running script)."""
    directory = boot_env.stage.path
    if case == "corrupt":
        (directory / HELPER_MARKER_NAME).write_text('{"helper_pid": 42', encoding="utf-8")
    elif case == "not_a_dict":
        (directory / HELPER_MARKER_NAME).write_text("[1, 2]", encoding="utf-8")
    else:
        _plant(directory)
        monkeypatch.setattr(install_marker, "process_identity", MagicMock(side_effect=OSError))
    _staged_files(directory)
    before = sorted(os.listdir(directory))

    boot.register()

    assert boot._delayed_init in boot_env.timers.registered
    assert boot._announce_and_quit not in boot_env.timers.registered
    assert (directory / HELPER_MARKER_NAME).exists()
    assert install_marker.live_marker(str(directory)) is None
    assert install_marker.guards_staging(str(directory))
    staging.purge_stale(staging.StagingDir(str(directory), True))
    assert sorted(os.listdir(directory)) == before
    # Older than any helper could still be: now it is stale like any other.
    _age(directory / HELPER_MARKER_NAME)
    assert not install_marker.guards_staging(str(directory))


def test_no_marker_is_a_normal_launch(boot_env):
    connector_installation.mark_updating()

    boot.register()

    assert list(boot_env.timers.registered) == [boot._delayed_init]
    connector_installation.started()  # the relaunched app's relay ends the window
    assert not connector_installation.updating()


def test_the_build_the_helper_is_installing_is_never_stopped(boot_env, monkeypatch):
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.4")
    _plant(boot_env.stage.path)

    boot.register()

    assert list(boot_env.timers.registered) == [boot._delayed_init]
    # The helper is still running, so its marker keeps guarding the purge.
    assert (boot_env.stage.path / HELPER_MARKER_NAME).exists()


def test_a_failing_check_starts_normally(boot_env, monkeypatch):
    _plant(boot_env.stage.path)
    monkeypatch.setattr(install_marker, "check_startup", MagicMock(side_effect=RuntimeError))

    boot.register()

    assert list(boot_env.timers.registered) == [boot._delayed_init]


def test_a_crashing_lookup_blocks_nothing_but_guards_the_purge(stage, monkeypatch):
    _plant(stage.path)
    monkeypatch.setattr(install_marker, "process_identity", MagicMock(side_effect=OSError))

    assert install_marker.live_marker(str(stage.path)) is None
    assert install_marker.check_startup("3.3.6") is None
    assert install_marker.guards_staging(str(stage.path))


def test_the_age_cap_covers_the_helpers_own_waits():
    assert HELPER_MARKER_MAX_AGE_S == 15 * 60
    assert HELPER_MARKER_MAX_AGE_S > HELPER_WAIT_FOR_EXIT_S + HELPER_WAIT_FOR_LOCKS_S
    assert MID_INSTALL_QUIT_DELAY_S < HELPER_WAIT_FOR_LOCKS_S


def test_the_startup_check_creates_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(staging, "_is_windows", lambda: False)
    monkeypatch.setattr(staging, "_posix_candidates", lambda: [(str(tmp_path), True)])

    assert install_marker.check_startup("3.3.6") is None
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# purge_stale
# ---------------------------------------------------------------------------


def test_purge_leaves_a_live_install_alone(stage):
    _plant(stage.path)
    _staged_files(stage.path)
    before = sorted(os.listdir(stage.path))

    staging.purge_stale(staging.StagingDir(str(stage.path), True),
                        keep_filenames=("Mixar-3.5.0.msi",))

    assert sorted(os.listdir(stage.path)) == before


def test_purge_clears_a_stale_marker_and_its_leftovers(stage):
    _plant(stage.path, helper_pid=5555)
    _staged_files(stage.path)

    staging.purge_stale(staging.StagingDir(str(stage.path), True))

    assert os.listdir(stage.path) == []


# ---------------------------------------------------------------------------
# The helpers delete it on every exit path, before the relaunch
# ---------------------------------------------------------------------------


def _windows_script():
    return win_installer.build_script(
        installer_path=r"C:\ProgramData\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\ProgramData\Mixar\Updates", version="3.4.0", pid=4242,
        relaunch_candidates=[r"C:\Program Files\Mixar\mixar-launcher.exe"],
        require_signature=True, signer_thumbprint="AB" * 20,
        install_dir=r"C:\Program Files\Mixar", system_dir=r"C:\Windows\System32",
    )


def _label(script, name):
    start = script.index(f"\n:{name}\n")
    following = re.search(r"\n:[a-z_]+\n", script[start + 1:])
    return script[start: start + 1 + following.start()] if following else script[start:]


def test_windows_helper_deletes_the_marker_on_every_exit_path():
    script = _windows_script()
    delete = 'del /f /q "%MARKER%" >nul 2>&1'
    marker = os.path.join(r"C:\ProgramData\Mixar\Updates", HELPER_MARKER_NAME)
    assert f'set "MARKER={marker}"' in script

    timeout = _label(script, "timeout")
    assert timeout.index(delete) < timeout.index("exit /b 2")
    finish = _label(script, "finish")
    # First thing in :finish, before the PowerShell that relaunches.
    assert finish.index(delete) < finish.index("Start-Process -FilePath $p[0]")
    assert finish.index(delete) < finish.index("goto relaunched")
    # Every other path ends in :finish: locked, a failed re-verify, the install.
    assert "goto finish" in _label(script, "locked")
    signature = script[script.index("re-check the signature"):script.index(":signature_ok")]
    assert "goto finish" in signature
    installed = _label(script, "installed")
    assert "goto " not in installed and "exit /b" not in installed  # falls into :finish
    # No exit before :finish other than the timeout's.
    head = script[:script.index("\n:finish\n")]
    assert [m.start() for m in re.finditer(r"exit /b", head)] == [head.index("exit /b 2")]
    assert script.count(delete) == 2


def test_macos_helper_deletes_the_marker_before_every_relaunch():
    script = mac_installer.build_script(
        installer_path="/Users/u/Library/Application Support/Mixar/Updates/Mixar-3.4.0.dmg",
        staging_dir="/Users/u/Library/Application Support/Mixar/Updates",
        target_bundle="/Applications/Mixar.app", version="3.4.0", pid=4242,
    )
    assert (f"MARKER='/Users/u/Library/Application Support/Mixar/Updates/"
            f"{HELPER_MARKER_NAME}'") in script
    relaunch = script[script.index("relaunch() {"):script.index("fail() {")]
    assert relaunch.index('rm -f "$MARKER"') < relaunch.index("/usr/bin/open")
    timeout = script[script.index("still running after"):]
    assert timeout.index('rm -f "$MARKER"') < timeout.index("exit 2")
    # Every other exit runs relaunch first: fail() and the success path.
    for exit_line in ("    exit 1\n", "\nexit 0\n"):
        before = script[:script.index(exit_line)]
        assert before.rstrip().endswith("relaunch")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell")
def test_macos_helper_runs_and_clears_the_marker(tmp_path):
    """The generated script itself: a failed unpack and the timeout both
    leave no marker behind (the relaunch target does not exist)."""
    for case in ("unpack", "timeout"):
        directory = tmp_path / case
        directory.mkdir()
        pid = os.getpid() if case == "timeout" else _exited_pid()
        script = mac_installer.build_script(
            installer_path=str(directory / "missing.zip"), staging_dir=str(directory),
            target_bundle=str(directory / "Nothing.app"), version="3.4.0", pid=pid,
        )
        script = script.replace(f"WAIT_SECONDS={HELPER_WAIT_FOR_EXIT_S}", "WAIT_SECONDS=0")
        (directory / HELPER_MARKER_NAME).write_text("{}")
        (directory / "helper.sh").write_text(script)

        process = subprocess.run(["/bin/sh", str(directory / "helper.sh")], timeout=60)

        assert process.returncode == (2 if case == "timeout" else 1)
        assert not (directory / HELPER_MARKER_NAME).exists(), case
        result = (directory / HELPER_RESULT_NAME).read_text()
        assert f"stage={'wait' if case == 'timeout' else 'unpack'}" in result


def _exited_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


# ---------------------------------------------------------------------------
# Real process identity (this platform)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="no creation time here")
def test_process_identity_tells_a_live_helper_from_a_gone_one():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        alive, created = install_marker.process_identity(child.pid)
        assert alive and created is not None
        assert install_marker.process_identity(child.pid) == (True, created)
    finally:
        child.kill()
        child.wait()
    assert install_marker.process_identity(child.pid)[0] is False


@pytest.mark.skipif(sys.platform != "darwin", reason="sysctl start time")
def test_macos_start_time_matches_ps():
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        started = install_marker._mac_started(child.pid)
        lstart = subprocess.run(["/bin/ps", "-o", "lstart=", "-p", str(child.pid)],
                                capture_output=True, text=True).stdout.strip()
        expected = time.strftime("%a %b %e %H:%M:%S %Y",
                                 time.localtime(int(float(started))))
        assert " ".join(lstart.split()) == " ".join(expected.split())
    finally:
        child.kill()
        child.wait()
