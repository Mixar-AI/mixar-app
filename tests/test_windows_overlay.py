# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows overlay regression fixtures and platform-independent safety checks."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "scripts/windows/overlay.bat"


def test_mirror_is_limited_to_mixar_package_and_preserves_exclusions():
    commands = OVERLAY.read_text().replace("^\n", " ").splitlines()
    mirrors = [line for line in commands if line.startswith("robocopy ") and "/MIR" in line]
    assert len(mirrors) == 1
    assert mirrors[0].startswith('robocopy "%SRC_DIR%\\scripts\\mixar" "%SOURCE_DIR%\\scripts\\mixar" /MIR ')
    for excluded in ('.venv', 'venv', '__pycache__', '.pytest_cache', '.DS_Store'):
        assert '"' + excluded + '"' in mirrors[0]
    script = OVERLAY.read_text()
    guard = 'if not exist "%SRC_DIR%\\scripts\\mixar\\" ('
    assert script.index(guard) < script.index('robocopy ')
    assert 'exit /b 1' in script.split(guard, 1)[1].split(')', 1)[0]
    mirror_check = script.split('echo Mirroring Mixar Python package...', 1)[1]
    assert 'if %errorlevel% geq 8 (' in mirror_check
    assert 'Error mirroring Mixar Python package' in mirror_check


@pytest.fixture
def windows_overlay(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Requires Windows robocopy")
    scripts = tmp_path / "scripts" / "windows"
    scripts.mkdir(parents=True)
    for name in ("overlay.bat", "settings.bat"):
        shutil.copy2(ROOT / "scripts" / "windows" / name, scripts / name)
    (tmp_path / "upstream").mkdir()
    (tmp_path / "src/scripts/mixar").mkdir(parents=True)
    env = dict(os.environ, MIXAR_UPSTREAM_DIR=str(tmp_path / "upstream"))

    def overlay(success=True):
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(scripts / "overlay.bat")],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result
    return overlay


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows robocopy")
def test_removed_override_restores_older_upstream_file(tmp_path, windows_overlay):
    relative = Path("source/blender/windowmanager/CMakeLists.txt")
    upstream = tmp_path / "upstream" / relative
    override = tmp_path / "src" / relative
    assembled = tmp_path / "source" / relative
    upstream.parent.mkdir(parents=True)
    override.parent.mkdir(parents=True)
    upstream.write_text("upstream target\n")
    override.write_text("branch glass target\n")
    os.utime(upstream, (1_000_000_000, 1_000_000_000))
    os.utime(override, (1_100_000_000, 1_100_000_000))
    windows_overlay()
    assert assembled.read_bytes() == override.read_bytes()
    override.unlink()  # Switching to a branch without this override.
    windows_overlay()
    assert assembled.read_bytes() == upstream.read_bytes()
    restored_mtime = assembled.stat().st_mtime_ns
    assert restored_mtime == upstream.stat().st_mtime_ns
    windows_overlay()
    assert assembled.stat().st_mtime_ns == restored_mtime


def test_removed_python_modules_do_not_return_in_incremental_build(tmp_path, windows_overlay):
    package = tmp_path / 'src/scripts/mixar'
    assembled = tmp_path / 'source/scripts/mixar'
    retired = ('modules/addon_project/ui/workspace_ops.py',
               'modules/space_mixie_chat/ui/header.py',
               'modules/space_mixie_chat/ui/removed_package/helpers.py')
    live = package / 'modules/addon_project/workspace.py'
    live.parent.mkdir(parents=True)
    live.write_text('CURRENT_WORKSPACE = True\n')
    for relative in retired:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('OBSOLETE_UI = True\n')
    stock = tmp_path / 'upstream/scripts/startup/bl_ui/stock.py'
    stock.parent.mkdir(parents=True)
    stock.write_text('UPSTREAM_UI = True\n')
    for folder in ('.venv', 'venv', '__pycache__', '.pytest_cache'):
        junk = package / folder / 'ignored.py'
        junk.parent.mkdir()
        junk.write_text('local only\n')
    (package / '.DS_Store').write_text('local only\n')
    windows_overlay()
    for relative in retired:
        assert (assembled / relative).exists()
        (package / relative).unlink()
    shutil.rmtree(package / 'modules/space_mixie_chat/ui/removed_package')
    timestamp = (assembled / live.relative_to(package)).stat().st_mtime_ns
    windows_overlay()
    assert all(not (assembled / relative).exists() for relative in retired)
    assert not (assembled / 'modules/space_mixie_chat/ui/removed_package').exists()
    assert (assembled / live.relative_to(package)).read_bytes() == live.read_bytes()
    assert (assembled / live.relative_to(package)).stat().st_mtime_ns == timestamp
    assert (tmp_path / 'source/scripts/startup/bl_ui/stock.py').read_bytes() == stock.read_bytes()
    for folder in ('.venv', 'venv', '__pycache__', '.pytest_cache', '.DS_Store'):
        assert not (assembled / folder).exists()


def test_missing_source_package_fails_before_purge(tmp_path, windows_overlay):
    assembled = tmp_path / 'source/scripts/mixar/keep.py'
    assembled.parent.mkdir(parents=True)
    assembled.write_text('must survive incomplete checkout\n')
    (tmp_path / 'src/scripts/mixar').rmdir()
    result = windows_overlay(success=False)
    assert 'Mixar script source directory is missing' in result.stdout
    assert assembled.read_text() == 'must survive incomplete checkout\n'
