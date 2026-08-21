# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Self-install eligibility, helper scripts, and restart planning.

The generated helper scripts are the part of this feature that cannot be
exercised in CI — they run after Blender is gone, on Windows and macOS —
so their text is pinned here instead: the PID wait, the elevation, the
unconditional relaunch, and the in-place bundle swap.
"""

import os
import sys
from pathlib import Path
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

from mixar.modules.common.updates.constants import InstallState
from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    installer,
    mac_installer,
    win_installer,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state


def _info(**overrides) -> UpdateInfo:
    defaults = dict(
        latest_version="3.4.0",
        current_version="3.3.6",
        download_url="https://cdn.example.com/releases/3.4.0/Mixar-3.4.0-x64.msi",
        download_sha256="a" * 64,
        download_size=420_000_000,
        installer_type="msi",
    )
    defaults.update(overrides)
    return UpdateInfo(**defaults)


def setup_function(_fn):
    get_update_state().set_idle()


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def _writable_location(monkeypatch, target="C:/Program Files/Mixar"):
    location = app_paths.InstallLocation(
        target, True, "", relaunch_candidates=[target + "/mixar-launcher.exe"],
    )
    monkeypatch.setattr(installer.app_paths, "get_install_location", lambda: location)
    return location


def test_windows_msi_release_is_eligible(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    _writable_location(monkeypatch)

    verdict = installer.check_eligibility(_info())

    assert verdict.ok is True
    assert verdict.extension == ".msi"


def test_release_without_a_checksum_is_refused(monkeypatch):
    """We are about to run this elevated; unverifiable means browser-only."""
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    _writable_location(monkeypatch)

    verdict = installer.check_eligibility(_info(download_sha256=""))

    assert verdict.ok is False
    assert "checksum" in verdict.reason


def test_release_without_an_installer_artifact_is_refused(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    _writable_location(monkeypatch)

    assert installer.check_eligibility(_info(download_url="")).ok is False


def test_wrong_installer_type_for_the_platform_is_refused(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    _writable_location(monkeypatch)

    verdict = installer.check_eligibility(_info(installer_type="dmg"))

    assert verdict.ok is False
    assert "dmg" in verdict.reason


def test_linux_is_never_eligible(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "linux")

    assert installer.check_eligibility(_info()).ok is False


def test_read_only_install_is_refused_with_its_reason(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "mac")
    monkeypatch.setattr(
        installer.app_paths, "get_install_location",
        lambda: app_paths.InstallLocation(
            "/Applications/Mixar.app", False, "No permission to update /Applications",
        ),
    )

    verdict = installer.check_eligibility(_info(installer_type="dmg"))

    assert verdict.ok is False
    assert verdict.reason == "No permission to update /Applications"


# ---------------------------------------------------------------------------
# macOS install location
# ---------------------------------------------------------------------------


def test_translocated_bundle_is_never_updated_in_place(monkeypatch):
    """Writes into an App Translocation mount vanish — refuse instead."""
    translocated = (
        "/private/var/folders/ab/AppTranslocation/XYZ/d/Mixar.app"
        "/Contents/MacOS/Mixar"
    )
    monkeypatch.setattr(app_paths, "_binary_path", lambda: translocated)

    location = app_paths._macos_location()

    assert location.writable is False
    assert "Applications" in location.reason


def test_macos_target_is_the_enclosing_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "Mixar.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    binary = bundle / "Contents" / "MacOS" / "Mixar"
    binary.write_text("")
    monkeypatch.setattr(app_paths, "_binary_path", lambda: str(binary))

    location = app_paths._macos_location()

    assert location.target == str(bundle)
    assert location.writable is True


def test_windows_relaunch_falls_back_to_the_default_directory(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    candidates = app_paths._windows_relaunch_candidates(r"C:\Program Files\Mixar 3.3")

    # os.path.join is the separator authority — these strings are built on
    # whatever platform the suite runs on; Windows joins with a backslash.
    assert candidates[0] == os.path.join(
        r"C:\Program Files\Mixar 3.3", "mixar-launcher.exe",
    )
    # An install that moves directories during the upgrade still comes back:
    # at least one candidate sits outside the version-stamped directory.
    assert any(
        candidate.endswith("mixar-launcher.exe") and "Mixar 3.3" not in candidate
        for candidate in candidates
    )


# ---------------------------------------------------------------------------
# Windows helper script
# ---------------------------------------------------------------------------


def _windows_script(**overrides):
    kwargs = dict(
        installer_path=r"C:\ProgramData\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\ProgramData\Mixar\Updates",
        version="3.4.0",
        pid=4242,
        relaunch_candidates=[r"C:\Program Files\Mixar\mixar-launcher.exe"],
        require_signature=False,
    )
    kwargs.update(overrides)
    return win_installer.build_script(**kwargs)


def test_windows_helper_waits_for_the_app_to_exit():
    script = _windows_script()

    assert 'tasklist /NH /FO CSV /FI "PID eq %PID%"' in script
    assert "goto waitloop" in script
    # A user who cancels the quit must not be updated out from under them.
    assert ":timeout" in script


def test_windows_helper_elevates_through_uac():
    script = _windows_script()

    assert "-Verb RunAs" in script
    assert "msiexec" in script
    # Fallback for a machine where PowerShell cannot be launched at all.
    assert '"%INSTALL_EXIT%"=="9009"' in script


def test_windows_helper_relaunches_even_when_the_install_fails():
    """A declined UAC prompt must leave the user with the old version, not none."""
    script = _windows_script()

    install_marker = script.index(":installed")
    relaunch = script.index('start "" "C:\\Program Files\\Mixar\\mixar-launcher.exe"')
    assert relaunch > install_marker
    assert "goto relaunched" in script


def test_windows_helper_only_rechecks_signatures_when_asked():
    assert "Get-AuthenticodeSignature" not in _windows_script()
    assert "Get-AuthenticodeSignature" in _windows_script(require_signature=True)


def test_windows_helper_writes_a_result_for_the_relaunched_app():
    script = _windows_script()

    assert "update-result.txt" in script
    assert "stage=install" in script
    assert "exit=%INSTALL_EXIT%" in script


def test_windows_helper_refuses_paths_that_break_batch_quoting(tmp_path):
    with pytest.raises(ValueError):
        win_installer.launch(
            installer_path=str(tmp_path / 'we"ird.msi'),
            staging_dir=str(tmp_path),
            version="3.4.0",
            relaunch_candidates=[str(tmp_path / "mixar.exe")],
        )


# ---------------------------------------------------------------------------
# macOS helper script
# ---------------------------------------------------------------------------


def _macos_script(**overrides):
    kwargs = dict(
        installer_path="/Users/x/Library/Application Support/Mixar/Updates/Mixar-3.4.0.dmg",
        staging_dir="/Users/x/Library/Application Support/Mixar/Updates",
        target_bundle="/Applications/Mixar.app",
        version="3.4.0",
        pid=777,
        expected_team="ABCDE12345",
        require_signature=True,
    )
    kwargs.update(overrides)
    return mac_installer.build_script(**kwargs)


def test_macos_helper_waits_then_mounts_and_swaps():
    script = _macos_script()

    assert 'while kill -0 "$PID"' in script
    assert "hdiutil attach" in script
    # Swap, never overwrite in place: a failed copy must leave the app intact.
    assert 'mv "$TARGET" "$OLD"' in script
    assert 'mv "$NEW" "$TARGET"' in script


def test_macos_helper_installs_over_the_running_bundle_path():
    """The DMG's own bundle name is ignored — the installed path wins."""
    script = _macos_script(target_bundle="/Applications/Mixar 3.3.app")

    assert "TARGET='/Applications/Mixar 3.3.app'" in script


def test_macos_helper_restores_the_old_bundle_if_the_swap_fails():
    script = _macos_script()

    assert 'mv "$OLD" "$TARGET"' in script
    assert "restoring previous version" in script


def test_macos_helper_checks_the_signing_team_before_replacing_anything():
    script = _macos_script()

    verify_at = script.index("codesign --verify")
    swap_at = script.index('mv "$TARGET" "$OLD"')
    assert verify_at < swap_at
    assert "ABCDE12345" in script


def test_macos_helper_skips_verification_for_unsigned_builds():
    script = _macos_script(require_signature=False, expected_team="")

    assert "REQUIRE_SIGNATURE=0" in script


def test_macos_helper_always_reopens_the_app():
    script = _macos_script()

    assert "/usr/bin/open" in script
    # Every failure path funnels through fail(), which relaunches.
    assert script.count("relaunch") >= 3


def test_macos_helper_quotes_paths_with_spaces():
    script = _macos_script()

    assert "INSTALLER='/Users/x/Library/Application Support/Mixar/Updates/Mixar-3.4.0.dmg'" in script


# ---------------------------------------------------------------------------
# Helper result parsing
# ---------------------------------------------------------------------------


def test_consume_result_reads_and_clears(tmp_path):
    result_file = tmp_path / "update-result.txt"
    result_file.write_text("version=3.4.0\nstage=install\nexit=0\n")

    result = installer.consume_result(str(tmp_path))

    assert result == {"version": "3.4.0", "stage": "install", "exit": "0"}
    assert installer.result_is_success(result) is True
    # Cleared on read: a one-off failure must not be reported forever.
    assert not result_file.exists()
    assert installer.consume_result(str(tmp_path)) is None


def test_reboot_required_counts_as_success():
    assert installer.result_is_success(
        {"version": "3.4.0", "stage": "install", "exit": "3010"},
    ) is True


def test_cancelled_and_aborted_installs_are_failures():
    assert installer.result_is_success(
        {"version": "3.4.0", "stage": "install", "exit": "1602"},
    ) is False
    assert installer.result_is_success(
        {"version": "3.4.0", "stage": "wait", "exit": "timeout"},
    ) is False


# ---------------------------------------------------------------------------
# Restart planning
# ---------------------------------------------------------------------------


def test_ready_installer_goes_straight_to_the_confirmation(tmp_path):
    state = get_update_state()
    state.set_available(_info())
    state.set_ready(str(tmp_path / "Mixar-3.4.0.msi"), True)

    assert install_flow.plan_restart() == "confirm"


def test_clicking_mid_download_records_the_intent():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()

    assert install_flow.plan_restart() == "waiting"
    assert state.install_requested is True


def test_no_self_install_falls_back_to_the_browser():
    state = get_update_state()
    state.set_available(_info())
    state.set_install_unsupported("In-app updates aren't supported on this platform")

    assert install_flow.plan_restart() == "browser"


def test_apply_refuses_when_the_staged_installer_vanished(tmp_path):
    state = get_update_state()
    state.set_available(_info())
    state.set_ready(str(tmp_path / "gone.msi"), True)

    started, message = install_flow.apply_and_restart()

    assert started is False
    assert "missing" in message
    assert state.install_state is InstallState.FAILED


def test_apply_refuses_before_the_download_finished():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()

    started, message = install_flow.apply_and_restart()

    assert started is False
    assert message


# ---------------------------------------------------------------------------
# Helper spawn flags (Windows UAT round 2)
# ---------------------------------------------------------------------------

WIN_INSTALLER_SRC = (
    SCRIPTS / "mixar" / "modules" / "common" / "updates" / "core"
    / "win_installer.py"
)


def test_windows_helper_runs_in_a_hidden_console_not_detached():
    """DETACHED_PROCESS gives cmd no console, so every console child the
    wait loop spawns each second (tasklist, find, ping) opens its own
    VISIBLE window — the flashing terminal seen on UAT. CREATE_NO_WINDOW
    is a hidden console all children inherit."""
    source = WIN_INSTALLER_SRC.read_text(encoding="utf-8")

    assert "_CREATE_NO_WINDOW = 0x08000000" in source
    # The old constant survives only in the comment explaining why not.
    assert "_DETACHED_PROCESS =" not in source
    assert "creationflags=flags" in source


def test_windows_helper_breaks_away_from_a_job_when_allowed():
    """A kill-on-close job object would kill the helper at the exact moment
    its work starts; a job that forbids breakaway must not block the update."""
    source = WIN_INSTALLER_SRC.read_text(encoding="utf-8")
    launch = source[source.index("def launch"):]

    assert "_CREATE_BREAKAWAY_FROM_JOB" in launch
    assert launch.index("| _CREATE_BREAKAWAY_FROM_JOB") < launch.index("except OSError")


def test_helper_launchers_return_the_process_handle():
    """apply_and_restart keeps the Popen so a quit that never happens can
    kill the helper instead of leaving it polling our PID for 5 minutes."""
    win = WIN_INSTALLER_SRC.read_text(encoding="utf-8")
    mac = (WIN_INSTALLER_SRC.parent / "mac_installer.py").read_text(encoding="utf-8")

    assert "return proc" in win[win.index("def launch"):]
    assert "return proc" in mac[mac.index("def launch"):]
