# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared set-up for running the macOS update helper for real (``/bin/sh``)
on throwaway bundles: an installed "old" ``Mixar.app``, a staged zip holding
a "new" one, and a fake ``codesign`` that reads a bundle's signature from
files inside it (``Contents/team``: its Team ID, ``not set`` for an ad hoc
signature; ``Contents/invalid``: a signature that fails ``--verify``).
"""

import subprocess
import sys
import zipfile
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

from mixar.modules.common.updates.constants import HELPER_MARKER_NAME, HELPER_RESULT_NAME
from mixar.modules.common.updates.core import mac_installer

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell")

_FAKE_CODESIGN = """#!/bin/sh
for last in "$@"; do :; done
case "$1" in
    --verify)
        [ -f "$last/Contents/team" ] && [ ! -f "$last/Contents/invalid" ] && exit 0
        echo "$last: invalid signature" >&2
        exit 1 ;;
    -dv)
        if [ -f "$last/Contents/team" ]; then
            echo "Executable=$last/Contents/MacOS/Mixar" >&2
            echo "TeamIdentifier=$(cat "$last/Contents/team")" >&2
            exit 0
        fi
        echo "$last: code object is not signed at all" >&2
        exit 1 ;;
esac
exit 2
"""


def exited_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def bundle(path, marker, team=None, invalid=False):
    """A bundle whose binary reads *marker*; *team* signs it (fake codesign)."""
    (path / "Contents" / "MacOS").mkdir(parents=True)
    (path / "Contents" / "MacOS" / "Mixar").write_text(marker)
    if team is not None:
        (path / "Contents" / "team").write_text(team)
    if invalid:
        (path / "Contents" / "invalid").write_text("")
    return path


def zip_of(app, destination):
    with zipfile.ZipFile(destination, "w") as archive:
        for file in app.rglob("*"):
            archive.write(file, Path(app.name) / file.relative_to(app))
    return destination


def staged_update(tmp_path, installed_team=None, new_team=None, new_invalid=False):
    """(staging, target, archive): the installed app and a staged zip."""
    staging = tmp_path / "Updates"
    staging.mkdir()
    applications = tmp_path / "Applications"
    applications.mkdir()
    target = bundle(applications / "Mixar.app", "old", team=installed_team)
    source = bundle(tmp_path / "build" / "Mixar.app", "new", team=new_team, invalid=new_invalid)
    archive = zip_of(source, staging / "Mixar-3.4.0.zip")
    (staging / HELPER_MARKER_NAME).write_text("{}")
    return staging, target, archive


@pytest.fixture(name="env")
def env_fixture(tmp_path):
    """Installed "old" Mixar.app, a staged zip holding a "new" one."""
    return staged_update(tmp_path)


def fake_codesign(directory):
    path = Path(directory) / "codesign"
    path.write_text(_FAKE_CODESIGN)
    path.chmod(0o755)
    return path


def helper_script(staging, target, archive, pid, codesign=None, **overrides):
    """The generated helper, written to *staging*: no reopen grace, and the
    fake ``codesign`` when given."""
    kwargs = dict(
        installer_path=str(archive), staging_dir=str(staging), target_bundle=str(target),
        version="3.4.0", pid=pid, relaunch=False, trigger="quit", from_version="3.3.6",
        attempt_id="abc",
    )
    kwargs.update(overrides)
    script = mac_installer.build_script(**kwargs)
    script = script.replace("REOPEN_GRACE_SECONDS=2", "REOPEN_GRACE_SECONDS=0")
    if codesign is not None:
        script = script.replace("CODESIGN=/usr/bin/codesign", f"CODESIGN={codesign}")
    path = Path(staging) / "helper.sh"
    path.write_text(script)
    return path


def result(staging):
    lines = (Path(staging) / HELPER_RESULT_NAME).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)
