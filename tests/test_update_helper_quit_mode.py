# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The update helpers' install-on-quit mode and their interruption contract.

The macOS helper is run for real (``/bin/sh``) on throwaway bundles: an
install on quit swaps the bundle and leaves Mixar closed, reopens it only
for a launch that was turned away (after that launch has exited), and a
TERM (logout, shutdown) always leaves a working app and records
``stage=interrupted``. The Windows helper is pinned on its text: helper v6
records the trigger and, installing on quit, stays closed (exit 4 from the
PowerShell finish step) unless a reopen was requested.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
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

from mixar.modules.common.updates.constants import (
    HELPER_LOG_NAME,
    HELPER_MARKER_NAME,
    HELPER_REOPEN_NAME,
)
from mixar.modules.common.updates.core import installer, mac_installer, win_installer
from update_helper_fixtures import POSIX
from update_helper_fixtures import bundle as _bundle
from update_helper_fixtures import env_fixture  # noqa: F401 - the `env` fixture
from update_helper_fixtures import exited_pid as _exited_pid
from update_helper_fixtures import helper_script as _script
from update_helper_fixtures import result as _result


@POSIX
def test_install_on_quit_swaps_and_leaves_mixar_closed(env):
    staging, target, archive = env
    script = _script(staging, target, archive, _exited_pid())

    assert subprocess.run(["/bin/sh", str(script)], timeout=60).returncode == 0

    assert (target / "Contents" / "MacOS" / "Mixar").read_text() == "new"
    assert _result(staging) == {"version": "3.4.0", "stage": "install", "exit": "0",
                                "trigger": "quit", "from_version": "3.3.6",
                                "attempt_id": "abc", "helper_version": "6"}
    log = (staging / HELPER_LOG_NAME).read_text()
    assert "installed on quit - Mixar stays closed" in log and "relaunching" not in log
    assert not (staging / HELPER_MARKER_NAME).exists()
    assert not archive.exists()
    assert not list(target.parent.glob(".mixar-update-*"))


def _orphan_sleep(seconds):
    """A process that is not our child (like a turned-away Mixar): it is
    reaped by launchd/init when it ends, so ``kill -0`` stops seeing it."""
    out = subprocess.run(["/bin/sh", "-c", f"/bin/sleep {seconds} >/dev/null 2>&1 & echo $!"],
                         capture_output=True, text=True, timeout=10).stdout
    return int(out.strip())


@POSIX
def test_a_turned_away_launch_is_waited_for_then_reopened(env):
    """Installing on quit, Mixar stays closed unless a launch was turned
    away; then it is reopened once that launch has gone. (The install
    fails and the target is elsewhere, so nothing is really opened.)"""
    staging, target, archive = env
    archive.write_bytes(b"not a zip")
    (staging / HELPER_REOPEN_NAME).write_text(f"{_orphan_sleep(3)}\n")
    script = _script(staging, target, archive, _exited_pid(),
                     target_bundle=str(target.parent / "Gone.app"))
    started = time.monotonic()

    assert subprocess.run(["/bin/sh", str(script)], timeout=60).returncode == 1

    assert time.monotonic() - started >= 2.5  # waited for the turned-away launch
    log = (staging / HELPER_LOG_NAME).read_text()
    assert "turned away during the update - reopening" in log
    assert "nothing to relaunch at" in log and "stays closed" not in log
    assert not (staging / HELPER_REOPEN_NAME).exists()


@POSIX
def test_a_failed_install_on_quit_stays_closed_and_says_why(env):
    staging, target, archive = env
    archive.write_bytes(b"not a zip")
    script = _script(staging, target, archive, _exited_pid())

    assert subprocess.run(["/bin/sh", str(script)], timeout=60).returncode == 1

    assert _result(staging)["stage"] == "unpack" and _result(staging)["trigger"] == "quit"
    assert "stays closed" in (staging / HELPER_LOG_NAME).read_text()
    assert (target / "Contents" / "MacOS" / "Mixar").read_text() == "old"
    assert not (staging / HELPER_MARKER_NAME).exists()


@POSIX
def test_a_term_while_waiting_records_interrupted_and_touches_nothing(env):
    staging, target, archive = env
    mixar = subprocess.Popen(["/bin/sleep", "30"])
    script = _script(staging, target, archive, mixar.pid)
    helper = subprocess.Popen(["/bin/sh", str(script)])
    try:
        time.sleep(1.5)
        helper.send_signal(signal.SIGTERM)
        assert helper.wait(timeout=30) == 3
    finally:
        mixar.kill()
        mixar.wait()

    assert _result(staging)["stage"] == "interrupted"
    assert (target / "Contents" / "MacOS" / "Mixar").read_text() == "old"
    assert not (staging / HELPER_MARKER_NAME).exists()


def _interrupted_function(script_text):
    start = script_text.index("log() {")
    end = script_text.index("trap interrupted TERM")
    return script_text[start:end]


@POSIX
@pytest.mark.parametrize("moment", ["moved_aside", "swapped"])
def test_a_term_mid_swap_leaves_a_working_app(env, moment):
    """The interrupted() handler itself, at the two moments that matter:
    the old bundle moved aside (it goes back) and the new one in place
    (that is a finished install)."""
    staging, target, archive = env
    text = _script(staging, target, archive, 1).read_text()
    old = target.parent / ".mixar-update-old-1.app"
    target.rename(old)
    swapped = "0"
    if moment == "swapped":
        _bundle(target, "new")
        swapped = "1"
    driver = staging / "driver.sh"
    driver.write_text(
        "#!/bin/sh\nset -u\n"
        + "\n".join(line for line in text.splitlines() if re.match(r"^[A-Z_]+=", line))
        + "\n" + _interrupted_function(text)
        + f'OLD="{old}"\nSWAPPED={swapped}\ninterrupted\n')

    assert subprocess.run(["/bin/sh", str(driver)], timeout=30).returncode == 3

    expected = "new" if moment == "swapped" else "old"
    assert (target / "Contents" / "MacOS" / "Mixar").read_text() == expected
    assert not old.exists()
    assert _result(staging)["stage"] == ("install" if moment == "swapped" else "interrupted")


@POSIX
def test_leftovers_of_a_killed_helper_are_cleared(env):
    staging, target, archive = env
    for leftover in (".mixar-update-new-99.app", ".mixar-update-old-98.app"):
        _bundle(target.parent / leftover, "stale")
    script = _script(staging, target, archive, _exited_pid())

    assert subprocess.run(["/bin/sh", str(script)], timeout=60).returncode == 0
    assert not list(target.parent.glob(".mixar-update-*"))


def test_restart_and_update_keeps_relaunching():
    script = mac_installer.build_script(
        installer_path="/u/Mixar.dmg", staging_dir="/u", target_bundle="/Applications/Mixar.app",
        version="3.4.0", pid=1)
    assert "RELAUNCH=1" in script and "TRIGGER=click" in script
    relaunch = script[script.index("relaunch() {"):script.index("fail() {")]
    # The stay-closed branch is the no-relaunch mode's only.
    assert relaunch.index('if [ "$RELAUNCH" != "1" ]') < relaunch.index("/usr/bin/open")
    assert "trap interrupted TERM" in script and "trap '' HUP INT" in script


def test_the_turned_away_wait_comes_before_the_swap():
    script = mac_installer.build_script(
        installer_path="/u/Mixar.dmg", staging_dir="/u", target_bundle="/Applications/Mixar.app",
        version="3.4.0", pid=1)
    body = script[script.index("# ---- swap the bundle"):]
    assert body.index("wait_for_turned_away") < body.index('mv "$TARGET" "$OLD"')


# ---------------------------------------------------------------------------
# Windows helper v6
# ---------------------------------------------------------------------------


def _windows(**overrides):
    kwargs = dict(
        installer_path=r"C:\ProgramData\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\ProgramData\Mixar\Updates", version="3.4.0", pid=4242,
        relaunch_candidates=[r"C:\Program Files\Mixar\mixar-launcher.exe"],
        require_signature=True, signer_thumbprint="AB" * 20,
        install_dir=r"C:\Program Files\Mixar", system_dir=r"C:\Windows\System32",
    )
    kwargs.update(overrides)
    return win_installer.build_script(**kwargs)


def test_windows_install_on_quit_stays_closed_unless_reopen_was_asked():
    script = _windows(relaunch=False, trigger="quit")

    assert 'set "RELAUNCHMODE=0"' in script and 'set "TRIGGER=quit"' in script
    reopen = os.path.join(r"C:\ProgramData\Mixar\Updates", HELPER_REOPEN_NAME)
    assert f'set "REOPEN={reopen}"' in script
    finish = script[script.index("\n:finish\n"):script.index("\n:relaunched\n")]
    assert 'if "%ERRORLEVEL%"=="4" goto stayclosed' in finish
    # Without PowerShell: the fallback relaunch only when asked to.
    assert finish.index('if not "%RELAUNCHMODE%"=="1" if not exist "%REOPEN%" goto stayclosed') < (
        finish.index('start "" "C:\\Program Files\\Mixar\\mixar-launcher.exe"'))
    assert "\n:stayclosed\n" in finish

    ps = win_installer._PS_FINISH
    assert ps.index("$go=$env:RELAUNCHMODE -eq '1'") < ps.index("Start-Process")
    assert "relaunch_kind=skipped" in ps and "exit 4" in ps
    assert ps.index("Wait-Process") < ps.index("Start-Process")


def test_windows_restart_and_update_still_relaunches():
    script = _windows()
    assert 'set "RELAUNCHMODE=1"' in script and 'set "TRIGGER=click"' in script
    assert ">>\"%RESULT%\" echo trigger=%TRIGGER%" in script


def test_windows_trigger_is_an_enum():
    with pytest.raises(ValueError):
        _windows(trigger="quit&calc")


def test_the_powershell_finish_step_fits_its_batch_quoting():
    snippet = win_installer._PS_FINISH
    assert '"' not in snippet and "%" not in snippet and "\n" not in snippet


def test_the_windows_finish_step_never_hands_an_unset_reopen_path_to_literalpath():
    # -LiteralPath refuses $null with a binding error instead of "no file".
    ps = win_installer._PS_FINISH
    assert "-LiteralPath $env:REOPEN" not in ps
    uses = [m.start() for m in re.finditer(r"-LiteralPath \$q\b", ps)]
    assert len(uses) == 4  # Test-Path, Get-Content and both Remove-Items
    for at in uses:  # each inside an `if($q ...)` of its own statement
        guard = ps.rfind("if($q", 0, at)
        assert guard != -1 and ";" not in ps[guard:at], ps[at - 80:at]


def _finish_variables():
    return set(re.findall(r"\$env:([A-Z_]+)", win_installer._PS_FINISH))


def test_the_windows_batch_sets_every_variable_its_finish_step_reads():
    script = _windows(relaunch=False, trigger="quit")
    missing = [name for name in sorted(_finish_variables()) if f'set "{name}=' not in script]
    assert not missing


def test_the_windows_probe_sets_every_variable_the_finish_step_reads(tmp_path, monkeypatch):
    # tests/test_windows_update_process.py runs the finish step through this
    # probe on Windows only; an unset variable there takes another branch.
    from tests.qa import windows_update_probe as probe

    class Ran(Exception):
        pass

    seen = []

    def powershell(script, env, timeout=30):
        seen.append(env)
        raise Ran

    monkeypatch.setattr(probe, "_powershell", powershell)
    with pytest.raises(Ran):
        probe.run_finish_case(win_installer, tmp_path / "default")
    assert seen[-1]["RELAUNCHMODE"] == "1"
    for mode in ("1", "0"):
        with pytest.raises(Ran):
            probe.run_finish_case(win_installer, tmp_path / mode, relaunch_mode=mode)
    for env in seen:
        assert _finish_variables() <= set(env), sorted(_finish_variables() - set(env))


def test_an_interrupted_attempt_is_classified_as_such():
    verdict = installer.classify_result(
        {"version": "3.4.0", "stage": "interrupted", "exit": "1"}, "3.3.6")
    assert verdict["outcome"] == "failed" and verdict["failure_reason"] == "interrupted"


def test_the_windows_steps_moved_out_but_still_resolve():
    from mixar.modules.common.updates.core import win_helper_ps

    for name in ("_PS_INSTALL", "_PS_VERIFY", "_PS_LOCKS", "_PS_END_CONNECTORS", "_PS_FINISH"):
        assert getattr(win_installer, name) is getattr(win_helper_ps, name)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
def test_generated_scripts_parse():
    for relaunch in (True, False):
        script = mac_installer.build_script(
            installer_path="/u/Mixar.dmg", staging_dir="/u",
            target_bundle="/Applications/Mixar.app", version="3.4.0", pid=1,
            relaunch=relaunch)
        assert subprocess.run(["sh", "-n"], input=script.encode(), timeout=30).returncode == 0
    assert os.path.basename(HELPER_REOPEN_NAME) == HELPER_REOPEN_NAME
