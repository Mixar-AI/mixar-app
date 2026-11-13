# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An install nobody asked for (on quit, at launch) needs a verified
signature pinned to the running app's own Team ID (issue 2079 review).

- ``verify`` says ``VERIFIED`` only for a validly signed disk image whose
  Team ID is the running app's, which must have one: an unsigned dev
  build, or one whose Team ID cannot be read, is ``UNVERIFIED``.
- ``silent_refusal`` refuses without that verdict and a signer.
- The helper re-reads the installed app's Team ID itself and refuses a new
  bundle not signed by it; only an unsigned dev build updated from Restart
  & Update installs unpinned, as before.
"""

import subprocess

from update_helper_fixtures import POSIX, exited_pid, fake_codesign, helper_script, result
from update_helper_fixtures import staged_update

import pytest

from mixar.modules.common.updates.constants import HELPER_LOG_NAME
from mixar.modules.common.updates.core import (
    app_paths,
    install_gate,
    installer,
    silent_install,
    verify,
)

APP, DMG = "/Applications/Mixar.app", "/u/Mixar-3.4.0.dmg"


def _macos(monkeypatch, *, dmg_valid=True, teams):
    monkeypatch.setattr(verify.os, "name", "posix")
    monkeypatch.setattr(verify.sys, "platform", "darwin")
    monkeypatch.setattr(verify, "_run", lambda argv: (0 if dmg_valid else 3, "codesign says"))
    monkeypatch.setattr(verify, "team_id", lambda path: teams[str(path)])


@pytest.mark.parametrize("app_team, dmg_valid, dmg_team, expected", [
    ("TEAM123", True, "TEAM123", verify.VERIFIED),
    # The running app has nothing to pin to: never silent.
    ("", True, "TEAM123", verify.UNVERIFIED),
    (None, True, "TEAM123", verify.UNVERIFIED),
    ("", False, "", verify.UNVERIFIED),
    # A signed app: anything but its own team is refused.
    ("TEAM123", True, "OTHER99", verify.REJECTED),
    ("TEAM123", True, "", verify.REJECTED),  # ad hoc
    ("TEAM123", False, "TEAM123", verify.REJECTED),
    ("TEAM123", True, None, verify.UNVERIFIED),
])
def test_macos_verifies_only_against_the_running_app_s_team(
        monkeypatch, app_team, dmg_valid, dmg_team, expected):
    _macos(monkeypatch, dmg_valid=dmg_valid, teams={APP: app_team, DMG: dmg_team})

    verdict, _detail, signer = verify.verify_installer(DMG, bundle_path=APP)

    assert verdict == expected
    assert signer == ("TEAM123" if expected == verify.VERIFIED else "")


def test_no_running_bundle_is_never_verified(monkeypatch):
    _macos(monkeypatch, teams={DMG: "TEAM123"})
    assert verify.verify_installer(DMG, bundle_path="")[0] == verify.UNVERIFIED


@pytest.mark.parametrize("verified, signer", [(False, ""), (True, ""), (False, "TEAM123")])
def test_the_silent_gate_needs_a_verdict_and_a_pinned_signer(monkeypatch, verified, signer):
    monkeypatch.setattr(install_gate, "silent_blocker", lambda e: "")
    location = app_paths.InstallLocation(APP, True, needs_elevation=False)
    eligibility = installer.Eligibility(True, location=location)

    assert "signature" in silent_install.silent_refusal(eligibility, verified=verified, signer=signer)
    assert "signature" in silent_install.silent_refusal(eligibility)
    assert silent_install.silent_refusal(eligibility, verified=True, signer="TEAM123") == ""


# ---------------------------------------------------------------------------
# The helper's own pin: the installed app's Team ID
# ---------------------------------------------------------------------------


def _run_helper(tmp_path, *, installed, new, require, expected_team="", new_invalid=False):
    staging, target, archive = staged_update(
        tmp_path, installed_team=installed, new_team=new, new_invalid=new_invalid)
    script = helper_script(staging, target, archive, exited_pid(),
                           codesign=fake_codesign(tmp_path),
                           require_signature=require, expected_team=expected_team)
    code = subprocess.run(["/bin/sh", str(script)], timeout=60).returncode
    installed_now = (target / "Contents" / "MacOS" / "Mixar").read_text()
    return code, installed_now, result(staging), (staging / HELPER_LOG_NAME).read_text()


@POSIX
def test_a_bundle_from_the_installed_app_s_team_installs(tmp_path):
    code, app, outcome, _log = _run_helper(
        tmp_path, installed="TEAM123", new="TEAM123", require=True, expected_team="TEAM123")
    assert (code, app, outcome["stage"]) == (0, "new", "install")


@POSIX
@pytest.mark.parametrize("installed, new, require, expected_team, new_invalid, says", [
    # Silent installs (require=1) and any signed installed app: same team only.
    ("TEAM123", "OTHER99", True, "TEAM123", False, "expected 'TEAM123'"),
    ("TEAM123", "not set", True, "TEAM123", False, "expected 'TEAM123'"),
    ("TEAM123", None, True, "TEAM123", False, "not validly signed"),
    ("TEAM123", "TEAM123", True, "TEAM123", True, "not validly signed"),
    # The app verified against TEAM123, but the installed app is not that one.
    ("OTHER99", "OTHER99", True, "TEAM123", False, "expected 'TEAM123'"),
    # Nothing to pin to: a silent install refuses.
    (None, "TEAM123", True, "", False, "could not read the installed app's Team ID"),
    ("not set", "TEAM123", True, "", False, "could not read the installed app's Team ID"),
    # Restart & Update unverified, but the installed app is signed: still pinned.
    ("TEAM123", None, False, "", False, "not validly signed"),
    ("TEAM123", "OTHER99", False, "", False, "expected 'TEAM123'"),
])
def test_the_helper_refuses_what_the_installed_app_s_team_did_not_sign(
        tmp_path, installed, new, require, expected_team, new_invalid, says):
    code, app, outcome, log = _run_helper(
        tmp_path, installed=installed, new=new, require=require,
        expected_team=expected_team, new_invalid=new_invalid)

    assert (code, app, outcome["stage"]) == (1, "old", "verify")
    assert says in log


@POSIX
def test_an_unsigned_dev_build_still_updates_from_restart_and_update(tmp_path):
    code, app, outcome, _log = _run_helper(tmp_path, installed=None, new=None, require=False)
    assert (code, app, outcome["stage"]) == (0, "new", "install")
