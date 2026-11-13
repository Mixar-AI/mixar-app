# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the app does around the move out of Program Files (#2079 review).

- Results in the shared staging folder are read only for this user's own
  attempts, or once at the first start after the move (``result_owner``).
- "Open with" entries follow the move (``assoc_repair``), and so does the
  GPU the user chose for Mixar in Windows' graphics settings
  (``gpu_preference``).
- An elevated install leaves the file type registration to the app's first
  normal start (``file_type_registration``).
- A learned 1625 is forgotten once installs without the prompt work again.
- The helper holds the installer open, and re-checks a signed one, until
  msiexec is done.
Pure functions, fakes and generated text only: the real registry, msiexec
and shortcuts run on the Windows QA box.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.updates import constants
from mixar.modules.common.updates.core import (
    assoc_repair,
    file_type_registration,
    gpu_preference,
    installer,
    result_owner,
    win_installer,
    win_msi,
    win_scope,
)

OLD = r"C:\Program Files\Mixar"
NEW = r"C:\Users\José\AppData\Local\Programs\Mixar"


@pytest.fixture
def config(monkeypatch):
    values = {}
    monkeypatch.setattr(result_owner, "_config", lambda: values)
    monkeypatch.setattr(result_owner, "_add_config", values.__setitem__)
    return values


# ---------------------------------------------------------------------------
# Whose result is this?
# ---------------------------------------------------------------------------


def test_this_users_attempts_are_remembered(config):
    for n in range(12):
        result_owner.remember_attempt(f"a{n}")
    result_owner.remember_attempt("a5")          # again: moves to the end, once
    result_owner.remember_attempt("")
    kept = config[constants.UPDATE_ATTEMPTS_CONFIG_KEY]
    assert len(kept) == constants.UPDATE_ATTEMPTS_KEPT and kept[-1] == "a5"
    assert kept.count("a5") == 1
    assert result_owner.own_attempt("a11") and result_owner.own_attempt("a5")
    assert not result_owner.own_attempt("a0") and not result_owner.own_attempt(None)


def test_the_first_start_after_the_move_is_once_per_install():
    first = result_owner.first_start_after_move
    assert first(NEW, OLD, None)
    assert not first(NEW, OLD, NEW.upper())
    assert first(NEW, OLD, r"C:\Users\José\AppData\Local\Programs\Older")
    assert not first(NEW, "", None)              # never moved


def test_another_accounts_result_is_left_unread(monkeypatch, config, tmp_path):
    """The shared ProgramData folder also holds the results of another
    account's Program Files Mixar (#2079 review)."""
    monkeypatch.setattr(result_owner, "_moved_from", lambda: OLD)
    (tmp_path / "update-result.txt").write_text(
        "version=4.5.0\nstage=install\nexit=0\nattempt_id=theirs\n")
    # The first start after the move reads the old app's result, once ...
    accept = result_owner.foreign_filter(NEW)
    assert installer.consume_result(str(tmp_path), accept=accept)["attempt_id"] == "theirs"
    assert config[constants.MOVE_RESULT_READ_CONFIG_KEY] == NEW
    # ... later starts read only this user's own attempts.
    (tmp_path / "update-result.txt").write_text(
        "version=4.5.1\nstage=install\nexit=0\nattempt_id=theirs2\n")
    accept = result_owner.foreign_filter(NEW)
    assert installer.consume_result(str(tmp_path), accept=accept) is None
    assert (tmp_path / "update-result.txt").exists()    # not deleted either
    result_owner.remember_attempt("theirs2")
    assert installer.consume_result(str(tmp_path), accept=accept)["version"] == "4.5.1"
    assert not (tmp_path / "update-result.txt").exists()


def test_a_broken_config_reads_only_own_attempts(monkeypatch, tmp_path):
    monkeypatch.setattr(result_owner, "_config", MagicMock(side_effect=OSError("x")))
    monkeypatch.setattr(result_owner, "_moved_from", lambda: OLD)
    accept = result_owner.foreign_filter(NEW)
    assert not accept({"attempt_id": "x"})


# ---------------------------------------------------------------------------
# "Open with"
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self, values):
        self.values = dict(values)
        self.written = {}

    def read(self, root, key, name=""):
        return self.values.get((root, key, name))

    def write(self, key, value, name=""):
        self.written[(key, name)] = value


def test_commands_are_matched_and_moved_case_insensitively():
    command = '"c:\\program files\\mixar\\mixar-launcher.exe" "%1"'
    assert assoc_repair.runs_from(command, OLD + "\\")
    assert not assoc_repair.runs_from(command, r"C:\Program Files\Mix")
    assert not assoc_repair.runs_from('"C:\\Program Files\\Mixar2\\mixar.exe"', OLD)
    assert assoc_repair.moved_command(command, OLD, NEW) == f'"{NEW}\\mixar-launcher.exe" "%1"'
    # A replacement with backslashes or group references stays literal.
    assert assoc_repair.moved_command(command, OLD, r"D:\1\g<0>") == (
        '"D:\\1\\g<0>\\mixar-launcher.exe" "%1"')


def test_open_with_follows_the_move(monkeypatch):
    monkeypatch.setattr(assoc_repair.os, "name", "nt")
    apps = "Software\\Classes\\Applications\\{}\\shell\\open\\command"
    registry = _FakeRegistry({
        ("HKCU", apps.format("mixar-launcher.exe"), ""): f'"{OLD}\\mixar-launcher.exe" "%1"',
        ("HKCU", apps.format("mixar.exe"), ""): '"D:\\Elsewhere\\mixar.exe" "%1"',
        ("HKCU", assoc_repair._USER_CHOICE, "ProgId"): "mixar.4.4",
        # The machine-wide ProgID the installer removed with the old folder.
        ("HKCR", "mixar.4.4\\shell\\open\\command", ""): None,
    })
    monkeypatch.setattr(assoc_repair, "_registry", registry)
    assert assoc_repair.repair_open_with(OLD, NEW) == 2
    launcher = f"{NEW}\\mixar-launcher.exe"
    assert registry.written == {
        (apps.format("mixar-launcher.exe"), ""): f'"{launcher}" "%1"',
        ("Software\\Classes\\mixar.4.4\\shell\\open\\command", ""): f'"{launcher}" "%1"',
        ("Software\\Classes\\mixar.4.4\\DefaultIcon", ""): f'"{launcher}", 1',
    }


def test_open_with_leaves_working_and_foreign_entries(monkeypatch):
    monkeypatch.setattr(assoc_repair.os, "name", "nt")
    registry = _FakeRegistry({
        ("HKCU", assoc_repair._USER_CHOICE, "ProgId"): "mixar.4.5",
        ("HKCR", "mixar.4.5\\shell\\open\\command", ""): f'"{NEW}\\mixar-launcher.exe" "%1"',
    })
    monkeypatch.setattr(assoc_repair, "_registry", registry)
    assert assoc_repair.repair_open_with(OLD, NEW) == 0
    registry.values[("HKCU", assoc_repair._USER_CHOICE, "ProgId")] = "Blender.Blend"
    assert assoc_repair.repair_open_with(OLD, NEW) == 0
    assert registry.written == {}


# ---------------------------------------------------------------------------
# GPU preference
# ---------------------------------------------------------------------------


def test_the_gpu_preference_follows_the_move():
    """Settings > System > Display > Graphics keys the choice by the program's
    full path: a laptop user who chose the discrete GPU for Mixar keeps it."""
    present = {f"{NEW}\\mixar.exe", f"{NEW}\\mixar-launcher.exe"}
    values = {
        f"{OLD}\\mixar.exe": "GpuPreference=2;",
        "c:\\program files\\mixar\\MIXAR-LAUNCHER.EXE": "GpuPreference=1;",
        f"{OLD}\\blender-launcher.exe": "GpuPreference=2;",  # gone from the new folder
        f"{OLD}\\lib\\helper.exe": "GpuPreference=2;",  # not directly in the old folder
        r"C:\Program Files\Mixar2\mixar.exe": "GpuPreference=2;",
        r"C:\Games\game.exe": "GpuPreference=2;",
        # One the user already set for the new copy wins.
        f"{NEW.upper()}\\MIXAR-LAUNCHER.EXE": "GpuPreference=0;",
    }
    assert gpu_preference.moved_preferences(values, OLD + "\\", NEW, present.__contains__) == {
        f"{NEW}\\mixar.exe": "GpuPreference=2;"}
    assert gpu_preference.moved_preferences(values, OLD, NEW, lambda path: False) == {}
    assert gpu_preference.moved_preferences({}, OLD, NEW, present.__contains__) == {}


def test_the_gpu_preference_repair_runs_with_the_shortcut_repair(monkeypatch):
    from mixar.modules.common.updates.core import shortcut_repair

    monkeypatch.setattr(gpu_preference.os, "name", "nt")
    monkeypatch.setattr(gpu_preference, "_read_preferences",
                        lambda: {f"{OLD}\\mixar.exe": "GpuPreference=2;"})
    written = {}
    monkeypatch.setattr(gpu_preference, "_write_preference", written.__setitem__)
    monkeypatch.setattr(gpu_preference, "_exists", lambda path: True)
    monkeypatch.setattr(assoc_repair, "repair_open_with", lambda old, new: 0)
    monkeypatch.setattr(shortcut_repair.subprocess, "run",
                        MagicMock(side_effect=OSError("no PowerShell here")))
    shortcut_repair._run(OLD, NEW)
    assert written == {f"{NEW}\\mixar.exe": "GpuPreference=2;"}
    # A failing registry never stops the shortcuts.
    monkeypatch.setattr(gpu_preference, "_read_preferences", MagicMock(side_effect=OSError))
    run = MagicMock(side_effect=OSError("no PowerShell here"))
    monkeypatch.setattr(shortcut_repair.subprocess, "run", run)
    shortcut_repair._run(OLD, NEW)
    assert run.called


# ---------------------------------------------------------------------------
# File types after an elevated install
# ---------------------------------------------------------------------------


def test_the_file_type_is_registered_by_a_normal_start_only():
    should = file_type_registration.should_register
    assert should(True, 1, NEW + r"\mixar.exe")     # default token (UAC off)
    assert should(True, 3, NEW + r"\mixar.exe")     # limited token
    assert not should(True, 2, NEW + r"\mixar.exe")  # elevated: waits
    assert not should(False, 3, NEW + r"\mixar.exe")
    assert not should(True, 3, "")


def test_the_registration_clears_the_request_only_when_it_worked(monkeypatch):
    cleared = MagicMock()
    monkeypatch.setattr(file_type_registration, "_clear", cleared)
    run = MagicMock(return_value=MagicMock(returncode=1))
    monkeypatch.setattr(file_type_registration.subprocess, "run", run)
    file_type_registration._run(NEW + r"\mixar.exe")
    assert run.call_args.args[0] == [NEW + r"\mixar.exe", "--register"]
    assert not cleared.called
    run.return_value = MagicMock(returncode=0)
    file_type_registration._run(NEW + r"\mixar.exe")
    cleared.assert_called_once_with()


# ---------------------------------------------------------------------------
# The 1625 lesson is forgotten when it no longer holds
# ---------------------------------------------------------------------------


@pytest.fixture
def scope_config(monkeypatch):
    import mixar.config.config as config_module

    values = {}
    monkeypatch.setattr(win_scope, "_config", lambda: values)
    monkeypatch.setattr(config_module, "add_config", values.__setitem__)
    return values


def test_a_learned_1625_keeps_the_policy_it_saw(scope_config):
    win_scope.remember_user_installs_blocked(1)
    assert scope_config[constants.USER_INSTALLS_BLOCKED_CONFIG_KEY] == {
        "blocked": True, "disable_msi": 1}
    assert win_scope.learned_user_installs_blocked()
    # An earlier build stored True.
    scope_config[constants.USER_INSTALLS_BLOCKED_CONFIG_KEY] = True
    assert win_scope.learned_user_installs_blocked()
    win_scope.forget_user_installs_blocked()
    assert not win_scope.learned_user_installs_blocked()


@pytest.mark.parametrize("seen, now, forgotten", [
    (1, 0, True),        # IT lifted the policy
    (None, 0, True),     # Windows Server default, now set to 0
    (1, 1, False),
    (1, None, False),    # still unset: keep asking
    (0, 0, False),       # a 1625 with the policy at 0: some other rule, no loop
])
def test_the_policy_lifted_forgets_the_1625(scope_config, seen, now, forgotten):
    win_scope.remember_user_installs_blocked(seen)
    assert win_scope.forget_when_policy_allows(now) is forgotten
    assert win_scope.learned_user_installs_blocked() is not forgotten


def test_the_plan_rereads_the_policy(monkeypatch, scope_config):
    win_scope.remember_user_installs_blocked(1)
    monkeypatch.setattr(win_msi, "disable_msi_value", lambda: 0)
    monkeypatch.setattr(win_msi, "user_installs_blocked_by_policy", lambda: False)
    monkeypatch.setattr(win_msi, "can_self_elevate", lambda: True)
    monkeypatch.setattr(win_msi, "profile_dirs", lambda: [r"C:\Users\José"])
    win_scope.plan_for(win_scope.SCOPE_PER_USER, NEW)
    assert not win_scope.learned_user_installs_blocked()


@pytest.mark.parametrize("stored, value", [
    (None, None), (0, 0), (1, 1), (2, 2), ("1", 1), ("garbage", -1),
])
def test_the_disable_msi_policy_is_read_as_set(monkeypatch, stored, value):
    fake = MagicMock()
    fake.KEY_READ = fake.KEY_WOW64_64KEY = 0
    if stored is None:
        fake.OpenKey.side_effect = OSError("absent")
    else:
        fake.QueryValueEx.return_value = (stored, 4)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert win_msi.disable_msi_value() == value


# ---------------------------------------------------------------------------
# The installer is held until msiexec is done
# ---------------------------------------------------------------------------


def _script(require_signature):
    profile = r"C:\Users\José\AppData\Local"
    return win_installer.build_script(
        installer_path=profile + r"\Mixar\Updates\Mixar-4.5.0.msi",
        staging_dir=profile + r"\Mixar\Updates", version="4.5.0", pid=4242,
        relaunch_candidates=[NEW + r"\mixar-launcher.exe"],
        require_signature=require_signature, signer_thumbprint="ab" * 20)


def test_the_installer_is_held_and_rechecked_before_msiexec():
    signed = _script(True)
    hold, verify = win_installer._PS_HOLD, win_installer._PS_HELD_VERIFY
    # Read-only sharing: nothing can replace or delete it while it is held.
    assert "[IO.File]::Open($env:MSI,'Open','Read','Read')" in hold
    assert "$s.SignerCertificate.Thumbprint -ne $env:SIGNER" in verify
    assert signed.index(hold) < signed.index(verify) < signed.index("Start-Process")
    # An unsigned build (no signature to check) is held all the same.
    unsigned = _script(False)
    assert hold in unsigned and verify not in unsigned


def test_a_failed_hold_or_recheck_installs_nothing():
    script = _script(True)
    assert 'if "%INSTALL_EXIT%"=="77" goto heldverify' in script
    block = script[script.index(":heldverify"):]
    block = block[:block.index("goto finish")]
    assert "call :result verify signature" in block
    assert 'del /f /q "%MSI%"' in block and 'set "INSTALL_EXIT=1"' in block
    # Reached only by its goto: the block before it ends with one.
    before = script[:script.index(":heldverify")].rstrip().splitlines()
    assert before[-1] == "goto finish"
