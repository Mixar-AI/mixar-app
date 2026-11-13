# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Windows update helper survives a non-ASCII profile name (#2079).

cmd.exe reads a batch file in the console's OEM code page (437 or 850 on
most machines), and since installs moved into the user's profile every
helper path holds the profile name. A cp1252 script turned "José" into
"JosÚ" (the result, log and marker went to folders that do not exist, and
the update was offered again forever) and could not encode "Дмитрий" at
all ("Could not start the updater"). Helper v8 keeps the script ASCII and
hands every path to cmd.exe through its (Unicode) environment.
"""

import re
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

from mixar.modules.common.updates.core import win_installer

PROFILES = [r"C:\Users\José", r"C:\Users\Дмитрий", r"C:\Users\王小明"]


def _arguments(profile):
    local = profile + r"\AppData\Local"
    return dict(
        installer_path=local + r"\Mixar\Updates\Mixar-4.5.0.msi",
        staging_dir=local + r"\Mixar\Updates",
        version="4.5.0",
        relaunch_candidates=[local + r"\Programs\Mixar\mixar-launcher.exe",
                             local + r"\Programs\Mixar\mixar.exe"],
        require_signature=True,
        signer_thumbprint="ab" * 20,
        install_dir=local + r"\Programs\Mixar",
        from_version="4.4.3",
        attempt_id="0123abcd",
        elevate=False,
        elevate_fallback=True,
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_the_script_is_ascii_and_names_no_path(profile):
    script = win_installer.build_script(pid=4242, system_dir=r"C:\Windows\System32",
                                        **_arguments(profile))
    assert script.isascii()
    assert profile.split("\\")[-1] not in script and "AppData" not in script
    # The variables the old script set from its own text now come from outside.
    for name in ("LOG", "MSI", "MSILOG", "MSIPREVLOG", "RESULT", "LOCKS", "MARKER",
                 "REOPEN", "INSTALLDIR", "RELAUNCH", "ELEVNOTE", "VERSION",
                 "FROM_VERSION", "ATTEMPT"):
        assert not re.search(rf'^set "{name}=', script, re.M), name


@pytest.mark.parametrize("profile", PROFILES)
def test_every_path_reaches_the_helper_through_its_environment(profile):
    env = win_installer.helper_environment(**_arguments(profile))
    staging = profile + r"\AppData\Local\Mixar\Updates"
    assert env["RESULT"] == staging + r"\update-result.txt"
    assert env["LOG"] == staging + r"\update.log"
    assert env["MARKER"] == staging + r"\update-in-progress.json"
    assert env["MSI"] == staging + r"\Mixar-4.5.0.msi"
    assert env["INSTALLDIR"] == profile + r"\AppData\Local\Programs\Mixar"
    assert env["RELAUNCH1"].endswith(r"\mixar-launcher.exe") and env["RELAUNCH2"].endswith(
        r"\mixar.exe")
    assert env["RELAUNCH3"] == ""
    assert env["RELAUNCH"] == env["RELAUNCH1"] + "|" + env["RELAUNCH2"]


def test_the_script_uses_the_paths_only_quoted():
    """A value from the environment is never re-parsed by cmd when quoted;
    unquoted, a space or bracket in a path would split the line."""
    script = win_installer.build_script(pid=1, system_dir=r"C:\Windows\System32",
                                        **_arguments(PROFILES[0]))
    for name in ("LOG", "MSI", "MSILOG", "MSIPREVLOG", "RESULT", "LOCKS", "MARKER",
                 "REOPEN", "INSTALLDIR", "ELEVNOTE") + tuple(f"RELAUNCH{i}" for i in range(1, 10)):
        for match in re.finditer(rf"%{name}%", script):
            before, after = script[match.start() - 1], script[match.end()]
            assert before == '"' and after == '"', (name, script[match.start() - 30:match.end() + 5])
    # The fallback relaunch is a goto chain, never a ( ... ) block a path could end.
    fallback = script[script.index("if not defined RELAUNCH1"):
                      script.index("No Mixar executable found")]
    assert "(" not in fallback and fallback.count('start "" "%RELAUNCH') == 2


@pytest.mark.parametrize("profile", PROFILES)
def test_launch_writes_an_ascii_script_and_passes_unicode_paths(monkeypatch, tmp_path, profile):
    started = []

    def popen(argv, **kwargs):
        started.append((argv, kwargs))
        return MagicMock(pid=7)

    monkeypatch.setattr(win_installer.subprocess, "Popen", popen)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    staging = tmp_path / profile.split("\\")[-1] / "Updates"
    staging.mkdir(parents=True)
    arguments = _arguments(profile)
    arguments.update(staging_dir=str(staging), installer_path=str(staging / "Mixar-4.5.0.msi"))

    win_installer.launch(**arguments)

    argv, kwargs = started[0]
    script = Path(argv[3]).read_bytes()
    assert script.isascii()
    env = kwargs["env"]
    assert env["INSTALLDIR"] == arguments["install_dir"]
    assert env["MSI"] == arguments["installer_path"]
    assert env["RESULT"].startswith(str(staging))
    # Empty values are left out, so cmd's "if defined" reads them as unset.
    assert "RELAUNCH3" not in env


def test_an_odd_version_never_reaches_the_script(tmp_path):
    with pytest.raises(ValueError):
        win_installer.launch(installer_path=str(tmp_path / "a.msi"), staging_dir=str(tmp_path),
                             version="4.5.0 & calc", relaunch_candidates=[])
