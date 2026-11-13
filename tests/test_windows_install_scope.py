# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the updater runs msiexec for each Windows install scope (#2079).

``win_scope.decide`` is the one place that decides; these pin its table,
how the helper carries the plan out (helper v7), how the next launch reads
what the installer refused, and the first-start shortcut repair after the
move out of Program Files. Pure functions and generated text only: the
real msiexec runs on the Windows QA box (mixar-qa-harness
``drivers/peruser_win.py``).
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.common.updates import constants
from mixar.modules.common.updates.core import (
    app_paths,
    install_gate,
    installer,
    shortcut_repair,
    staging,
    state,
    win_installer,
    win_processes as wp,
    win_scope,
    win_signer,
)

PROFILE = r"C:\Users\ana\AppData\Local"
PER_USER_DIR = PROFILE + r"\Programs\Mixar"
PROGRAM_FILES_DIR = r"C:\Program Files\Mixar"


def _decide(scope, install_dir, *, blocked=False, self_elevate=True):
    return win_scope.decide(scope, install_dir, [PROFILE, r"C:\Users\ana"],
                            user_installs_blocked=blocked, can_self_elevate=self_elevate)


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def test_a_per_user_install_in_the_profile_needs_no_prompt():
    plan = _decide("per_user", PER_USER_DIR)
    assert (plan.needs_elevation, plan.elevate, plan.msi_properties) == (False, False, "")
    assert plan.elevate_fallback is True and plan.blocked_reason == ""
    # A standard user's prompt would run msiexec as someone else: no retry.
    assert _decide("per_user", PER_USER_DIR, self_elevate=False).elevate_fallback is False


def test_policy_that_refuses_user_installs_asks_or_sends_to_the_download():
    plan = _decide("per_user", PER_USER_DIR, blocked=True)
    assert (plan.needs_elevation, plan.elevate, plan.blocked_reason) == (True, True, "")
    refused = _decide("per_user", PER_USER_DIR, blocked=True, self_elevate=False)
    assert refused.blocked_reason == win_scope.POLICY_NEEDS_ADMIN


def test_a_machine_install_elevates_with_allusers():
    plan = _decide("machine", PROGRAM_FILES_DIR)
    assert (plan.needs_elevation, plan.elevate, plan.msi_properties) == (True, True, "ALLUSERS=1")
    assert plan.elevate_fallback is False


@pytest.mark.parametrize("scope, install_dir", [
    ("per_user", PROGRAM_FILES_DIR),   # every release before #2079: the move
    ("", PER_USER_DIR),                # Windows Installer could not tell
    ("", PROGRAM_FILES_DIR),
])
def test_anything_else_elevates_as_before(scope, install_dir):
    plan = _decide(scope, install_dir)
    assert (plan.needs_elevation, plan.elevate, plan.elevate_fallback, plan.msi_properties) == (
        True, True, False, "")


def test_the_scope_is_the_product_installed_where_this_copy_runs():
    products = [
        {"scope": "machine", "location": PROGRAM_FILES_DIR + "\\"},
        {"scope": "per_user", "location": PER_USER_DIR + "\\"},
    ]
    assert win_scope.scope_of(PER_USER_DIR, products) == "per_user"
    assert win_scope.scope_of(PROGRAM_FILES_DIR, products) == "machine"
    assert win_scope.scope_of(r"D:\Portable\Mixar", products) == ""
    assert win_scope.scope_of(PER_USER_DIR, None) == ""


def test_the_location_carries_the_plan(monkeypatch):
    monkeypatch.setattr(app_paths, "_binary_path", lambda: PER_USER_DIR + r"\mixar.exe")
    monkeypatch.setattr(app_paths.os.path, "abspath", lambda p: p)
    monkeypatch.setattr(app_paths.os.path, "dirname", lambda p: PER_USER_DIR)
    monkeypatch.setattr(app_paths, "_windows_scope", lambda install_dir: "per_user")
    monkeypatch.setattr(win_scope, "plan_for", lambda scope, d: _decide(scope, d))

    location = app_paths._windows_location()
    assert (location.kind, location.scope, location.writable) == ("msi", "per_user", True)
    assert (location.needs_elevation, location.elevate, location.elevate_fallback) == (
        False, False, True)

    monkeypatch.setattr(win_scope, "plan_for",
                        lambda scope, d: _decide(scope, d, blocked=True, self_elevate=False))
    location = app_paths._windows_location()
    assert location.writable is False and location.reason == win_scope.POLICY_NEEDS_ADMIN


def test_the_upgrade_code_is_the_one_packaging_derives():
    namespace = uuid.UUID("A83F2E1B-7C4D-4E5F-9B6A-1D2E3F4A5B6C")
    expected = "{%s}" % str(uuid.uuid5(namespace, "Mixar")).upper()
    assert constants.MSI_UPGRADE_CODE == expected
    cmake = (ROOT / "src" / "build_files" / "cmake" / "packaging.cmake").read_text()
    assert 'set(MIXAR_NAMESPACE_GUID "A83F2E1B-7C4D-4E5F-9B6A-1D2E3F4A5B6C")' in cmake


# ---------------------------------------------------------------------------
# The helper (v7)
# ---------------------------------------------------------------------------


def _script(**overrides):
    kwargs = dict(
        installer_path=PROFILE + r"\Mixar\Updates\Mixar-4.5.0.msi",
        staging_dir=PROFILE + r"\Mixar\Updates",
        version="4.5.0", pid=4242,
        relaunch_candidates=[PER_USER_DIR + r"\mixar-launcher.exe"],
        require_signature=False,
    )
    kwargs.update(overrides)
    return win_installer.build_script(**kwargs)


def test_the_helper_carries_the_plan():
    script = _script(elevate=False, elevate_fallback=True)
    assert 'set "ELEVATE=0"' in script and 'set "ELEVATEFALLBACK=1"' in script
    assert 'set "MSIPROPS="' in script
    assert f'set "UPGRADECODE={constants.MSI_UPGRADE_CODE}"' in script
    machine = _script(elevate=True, elevate_fallback=True, msi_properties="ALLUSERS=1")
    # The retry is for an unelevated run only.
    assert 'set "ELEVATE=1"' in machine and 'set "ELEVATEFALLBACK=0"' in machine
    assert 'set "MSIPROPS=ALLUSERS=1"' in machine
    # The no-PowerShell fallback passes the scope too.
    assert "LAUNCHAPP=0 %MSIPROPS% /l*v" in machine
    # Defaults are the pre-v7 behaviour: elevated, no properties.
    assert 'set "ELEVATE=1"' in _script() and "helper_version=8" in _script()


@pytest.mark.parametrize("props", ["ALLUSERS=1 & calc", "allusers=1", "A=1;B", '"X=1"'])
def test_only_plain_properties_reach_msiexec(props):
    with pytest.raises(ValueError):
        _script(msi_properties=props)


def test_the_helper_runs_msiexec_unelevated_and_retries_1625_once():
    ps = win_installer._PS_INSTALL
    assert "$up=$env:ELEVATE -ne '0'" in ps   # missing means elevated, as before
    unelevated = ps[ps.index("else{$p=Start-Process"):]
    assert "-Verb RunAs" not in unelevated[:unelevated.index("}")]
    assert "if($rc -eq 1625 -and -not $up -and $env:ELEVATEFALLBACK -eq '1')" in ps
    assert ps.count("Inst $true") == 1
    assert "foreach($x in (([string]$env:MSIPROPS) -split ' ')){if($x){$a+=$x}}" in ps
    for note in ("elevation=none", "elevation=runas", "elevation=fallback"):
        assert note in ps
    script = _script()
    assert 'type "%ELEVNOTE%" >>"%RESULT%" 2>nul' in script


def test_the_helper_asks_windows_installer_and_records_the_refusal():
    finish = win_installer._PS_FINISH
    assert "New-Object -ComObject WindowsInstaller.Installer" in finish
    assert "$w.RelatedProducts($env:UPGRADECODE)" in finish
    # The Uninstall key is only the fallback.
    assert finish.index("RelatedProducts") < finish.index("Get-ItemProperty")
    assert "if($k.Count -eq 0)" in finish
    assert f"{constants.MSI_REFUSAL_PROPERTY} property. Its value is" in finish
    assert "msi_refusal=" in finish


def test_begin_install_offers_the_retry_only_after_a_click(monkeypatch):
    launched = MagicMock()
    monkeypatch.setattr(win_installer, "launch", launched)
    monkeypatch.setattr(installer.os, "name", "nt")
    # An install nobody asked for needs this app's own signer (test_windows_signer_pin).
    monkeypatch.setattr(win_signer, "app_subject", lambda: "CN=MIXAR INC")
    location = app_paths.InstallLocation(
        PER_USER_DIR, True, needs_elevation=False, scope="per_user",
        elevate=False, elevate_fallback=True)
    for trigger, fallback in (("click", True), ("quit", False), ("launch", False)):
        installer.begin_install(
            installer_path="x.msi", staging_dir="s", version="4.5.0",
            eligibility=installer.Eligibility(True, location=location), verified=True,
            signer_thumbprint="AB12", trigger=trigger)
        kwargs = launched.call_args.kwargs
        assert (kwargs["elevate"], kwargs["elevate_fallback"], kwargs["msi_properties"]) == (
            False, fallback, "")


def test_the_one_helper_guard_leaves_the_1625_retry_to_that_helper(monkeypatch):
    """After a click, the prompted retry of a 1625 is a second msiexec that
    the same helper starts (``Inst $true``) once Mixar has quit: it never
    needs a second helper, so ``install_start``'s one helper per process
    cannot block it. A second helper in the same process is still refused."""
    from mixar.modules.common.updates.core import install_marker, install_start, result_owner

    launched = MagicMock(return_value=MagicMock(pid=4242))
    monkeypatch.setattr(win_installer, "launch", launched)
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(win_signer, "app_subject", lambda: "")
    monkeypatch.setattr(install_start, "_started", {"proc": None})
    monkeypatch.setattr(install_start, "_connector_updating", lambda updating: None)
    monkeypatch.setattr(result_owner, "remember_attempt", lambda attempt_id: None)
    for name in ("clear_reopen_requests", "write", "remove"):
        monkeypatch.setattr(install_marker, name, lambda *args, **kwargs: None)
    location = app_paths.InstallLocation(
        PER_USER_DIR, True, needs_elevation=False, scope="per_user",
        elevate=False, elevate_fallback=True)
    click = dict(installer_path=PROFILE + r"\Mixar\Updates\Mixar-4.5.0.msi", version="4.5.0",
                 eligibility=installer.Eligibility(True, location=location), verified=True,
                 signer="AB12", trigger="click", relaunch=True)

    proc = install_start.start_helper(**click)
    assert launched.call_count == 1
    assert launched.call_args.kwargs["elevate_fallback"] is True
    retry = win_installer._PS_INSTALL[win_installer._PS_INSTALL.index("if($rc -eq 1625"):]
    assert retry.index("$rc=Inst $true") < retry.index("exit $rc")
    with pytest.raises(RuntimeError):
        install_start.start_helper(**click)
    assert launched.call_count == 1
    install_start.stop_helper(proc, click["installer_path"])
    assert not install_start.helper_started()


# ---------------------------------------------------------------------------
# The next launch
# ---------------------------------------------------------------------------


def test_a_refusal_and_a_policy_block_are_their_own_failures():
    base = {"version": "4.5.0", "stage": "install"}
    assert installer.classify_result(
        dict(base, exit="1603", msi_refusal="machine"), "4.4.3")["failure_reason"] == "scope_refused"
    assert installer.classify_result(
        dict(base, exit="1625"), "4.4.3")["failure_reason"] == "policy_blocked"
    assert installer.classify_result(
        dict(base, exit="1603"), "4.4.3")["failure_reason"] == "msi_error"


def test_a_refused_version_is_offered_as_a_download(monkeypatch):
    # The real dataclass: the version lives in latest_version.
    info = state.UpdateInfo(latest_version="4.5.0", download_url="https://x/Mixar.msi",
                            download_sha256="ab", installer_type="msi")
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(app_paths, "get_install_location",
                        lambda: app_paths.InstallLocation(PER_USER_DIR, True))
    monkeypatch.setattr(win_scope, "refused_version", lambda: ("4.5.0", "machine"))
    assert not installer.check_eligibility(info)
    monkeypatch.setattr(win_scope, "refused_version", lambda: ("4.4.9", "machine"))
    assert installer.check_eligibility(info)


def test_the_report_remembers_what_the_attempt_taught(monkeypatch):
    from mixar.modules.common.updates.core import result_report

    refused, blocked, forgot = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(win_scope, "remember_refusal", refused)
    monkeypatch.setattr(win_scope, "remember_user_installs_blocked", blocked)
    monkeypatch.setattr(win_scope, "forget_user_installs_blocked", forgot)
    monkeypatch.setattr(result_report, "_disable_msi", lambda: 1)
    result_report._learn({"msi_refusal": "needs_admin"}, "scope_refused", "4.5.0")
    refused.assert_called_once_with("4.5.0", "needs_admin")
    result_report._learn({}, "policy_blocked", "4.5.0")
    # The policy seen with the 1625 is kept with it.
    blocked.assert_called_once_with(1)
    result_report._learn({}, "msi_error", "4.5.0")
    assert refused.call_count == 1 and blocked.call_count == 1
    # A 1625 the helper retried with the prompt: installed, but ask at once next time.
    result_report._learn({"elevation": "fallback"}, "", "4.5.0")
    assert blocked.call_count == 2
    assert not forgot.called
    # An install that worked without the prompt unlearns it (#2079 review).
    result_report._learn({"elevation": "none", "stage": "install", "exit": "0"}, "", "4.5.0")
    forgot.assert_called_once_with()
    result_report._learn({"elevation": "runas", "stage": "install", "exit": "0"}, "", "4.5.0")
    result_report._learn({"elevation": "none", "stage": "install", "exit": "1603"}, "msi_error",
                         "4.5.0")
    assert forgot.call_count == 1


def test_results_are_read_from_every_staging_directory(monkeypatch, tmp_path):
    from mixar.modules.common.updates.core import install_flow, result_owner

    mine, shared = tmp_path / "local", tmp_path / "shared"
    mine.mkdir()
    shared.mkdir()
    (shared / "update-result.txt").write_text(
        "version=4.5.0\nstage=install\nexit=0\nattempt_id=mine1\n")
    monkeypatch.setattr(staging, "resolve_staging_dir", lambda: staging.StagingDir(str(mine), True))
    monkeypatch.setattr(staging, "_is_windows", lambda: True)
    monkeypatch.setattr(staging, "existing_staging_dirs", lambda: [str(mine), str(shared)])
    config = {"update_attempt_ids": ["mine1"]}
    monkeypatch.setattr(result_owner, "_config", lambda: config)
    monkeypatch.setattr(result_owner, "_add_config", config.__setitem__)
    monkeypatch.setattr(result_owner, "_moved_from", lambda: "")

    result = install_flow.read_previous_result()
    assert result["version"] == "4.5.0" and result["staging_dir"] == str(shared)
    assert not (shared / "update-result.txt").exists()
    assert install_flow.read_previous_result() is None


def test_a_per_user_install_stages_in_its_own_profile(monkeypatch):
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    monkeypatch.setenv("LOCALAPPDATA", PROFILE)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\ana")
    monkeypatch.setattr(staging.sys, "executable", PER_USER_DIR + r"\5.2\python\bin\python.exe")
    roots = [root for root, _shared in staging._windows_candidates()]
    assert roots[:2] == [PROFILE, r"C:\ProgramData"]
    monkeypatch.setattr(staging.sys, "executable", PROGRAM_FILES_DIR + r"\5.2\python\bin\python.exe")
    candidates = staging._windows_candidates()
    assert candidates[:2] == [(r"C:\ProgramData", True), (PROFILE, False)]


def test_a_per_user_staging_folder_is_never_opened_to_other_accounts(monkeypatch, tmp_path):
    local = tmp_path / "Local"
    local.mkdir()
    monkeypatch.setattr(staging, "_is_windows", lambda: True)
    monkeypatch.setattr(staging, "_resolved", None)
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(staging.sys, "executable", str(local / "Programs" / "Mixar" / "python.exe"))
    granted = []
    monkeypatch.setattr(staging, "_grant_machine_read", granted.append)
    resolved = staging.resolve_staging_dir()
    assert resolved.path.startswith(str(local)) and granted == []
    # Any other install still opens the shared folder to every account.
    monkeypatch.setattr(staging, "_resolved", None)
    monkeypatch.setattr(staging.sys, "executable", str(tmp_path / "Program Files" / "python.exe"))
    (tmp_path / "ProgramData").mkdir()
    resolved = staging.resolve_staging_dir()
    assert resolved.path.startswith(str(tmp_path / "ProgramData")) and len(granted) == 1


# ---------------------------------------------------------------------------
# Install on quit: own background work does not block it
# ---------------------------------------------------------------------------

MIXAR = PER_USER_DIR + r"\mixar.exe"
PYTHON = PER_USER_DIR + r"\5.2\python\bin\python.exe"


def _row(pid, ppid, name, path="", window=False):
    return {"pid": pid, "ppid": ppid, "name": name, "path": path, "created": pid,
            "has_window": window}


def test_the_silent_gate_leaves_out_only_our_own_descendants():
    table = [
        _row(100, 1, "mixar.exe", MIXAR, window=True),   # us
        _row(101, 100, "mixar.exe", MIXAR),              # our render worker
        _row(102, 101, "python.exe", PYTHON),            # and its python
        _row(200, 1, "mixar.exe", MIXAR),                # a windowless Mixar of its own
        _row(300, 1, "mixar.exe", MIXAR, window=True),   # another Mixar window
    ]
    every = [(h.kind, h.pid) for h in wp.classify(table, PER_USER_DIR, 100)]
    assert (wp.BACKGROUND, 101) in every and (wp.BACKGROUND, 102) in every
    silent = [(h.kind, h.pid) for h in wp.classify(table, PER_USER_DIR, 100, descendants=False)]
    assert silent == [(wp.BACKGROUND, 200), (wp.MIXAR_WINDOW, 300)]


def test_the_silent_gate_refuses_when_the_table_is_unknown(monkeypatch):
    location = app_paths.InstallLocation(PER_USER_DIR, True, needs_elevation=False)
    eligibility = installer.Eligibility(True, location=location)
    monkeypatch.setattr(install_gate, "_is_windows", lambda: True)
    monkeypatch.setattr(wp, "_process_table", MagicMock(side_effect=OSError("denied")))
    assert install_gate.silent_blocker(eligibility) == "process table unavailable"
    # Restart & Update still goes ahead (the helper's wait guards it).
    assert wp.blocking_apps(PER_USER_DIR, 100) == []


# ---------------------------------------------------------------------------
# Shortcuts after the move
# ---------------------------------------------------------------------------


def test_shortcuts_are_repaired_once_after_the_move():
    assert shortcut_repair.should_repair(PER_USER_DIR, PROGRAM_FILES_DIR, None)
    assert not shortcut_repair.should_repair(PER_USER_DIR, "", None)    # never moved
    assert not shortcut_repair.should_repair(
        PER_USER_DIR, PROGRAM_FILES_DIR, PER_USER_DIR.upper())          # done
    assert not shortcut_repair.should_repair(
        PROGRAM_FILES_DIR, PROGRAM_FILES_DIR, None)                     # still there
    # A custom folder the install left is the old folder too (#2079 review).
    assert shortcut_repair.should_repair(PER_USER_DIR, r"D:\Tools\Mixar", None)


def test_the_repair_touches_only_mixar_launchers_in_the_old_folder():
    ps = shortcut_repair._PS_REPAIR
    assert "$names=@('mixar-launcher.exe','mixar.exe','blender-launcher.exe')" in ps
    assert "if($b.Contains('\\') -or ($names -notcontains $b.ToLower())){continue}" in ps
    # Another account's copy may keep the old launcher alive: this account's
    # pins follow its own copy all the same (#2079 review).
    assert "Test-Path -LiteralPath $t)" not in ps
    assert "if(-not (Test-Path -LiteralPath $nt -PathType Leaf)){continue}" in ps
    assert "Quick Launch" in ps and "Start Menu\\Programs" in ps and "'Desktop'" in ps
    # Taskbar pins are in Quick Launch\User Pinned, a hidden folder: without -Force
    # Get-ChildItem neither lists nor recurses into it (box run 20261112-175340).
    assert "Get-ChildItem -LiteralPath $r[0] -Filter *.lnk -File -Force " in ps
    # Paths come from the environment, never the script text.
    assert "$env:MIXAR_OLD_DIR" in ps and "$env:MIXAR_NEW_DIR" in ps
