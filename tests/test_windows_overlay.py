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
    for excluded in ('.venv', 'venv', '__pycache__', '.pytest_cache', '.DS_Store', '_build_env.py'):
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
    for name in ("overlay.bat", "settings.bat", "prune_overlay.ps1"):
        shutil.copy2(ROOT / "scripts" / "windows" / name, scripts / name)
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream/CMakeLists.txt").write_text("# Blender fixture\n")
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
    (tmp_path / "upstream" / "CMakeLists.txt").write_text("# Blender fixture\n")
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


PRUNE = Path(__file__).resolve().parents[1] / "scripts/windows/prune_overlay.ps1"


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def prune_tree(tmp_path):
    root = tmp_path / "overlay project with spaces"
    upstream, src, source = [root / folder for folder in ("upstream", "src", "source")]
    for directory in (upstream, src, source):
        directory.mkdir(parents=True)
    write_file(upstream / "CMakeLists.txt", "# Blender fixture\n")
    return root, upstream, src, source


def run_prune(tree, source=None, upstream=None):
    root, selected_upstream, src, selected_source = tree
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(PRUNE), "-RootDir", str(root),
         "-SourceDir", str(source or selected_source),
         "-UpstreamDir", str(upstream or selected_upstream), "-SrcDir", str(src)],
        capture_output=True, text=True,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell helper")
def test_orphans_archived_without_touching_inputs_objects_or_generated_headers(prune_tree):
    root, upstream, src, source = prune_tree
    current = "intern/ghost/GHOST_CallbackEventConsumer.hh"
    shadow = "intern/ghost/intern/GHOST_CallbackEventConsumer.hh"
    removed = "scripts/mixar/modules/removed_module.py"
    upstream_header = write_file(upstream / current, "new upstream header")
    mixar_module = write_file(src / "scripts/mixar/modules/current.py", "current overlay module")
    retained = [
        upstream_header,
        mixar_module,
        write_file(source / current, "new upstream header"),
        write_file(source / "scripts/mixar/modules/current.py", "current overlay module"),
        write_file(source / "source/creator/mixar_env_config.h", "stable generated header"),
        write_file(source / "scripts/mixar/config/_build_env.py", "stable generated Python marker"),
        write_file(root / "build/Dev/source/CMakeFiles/lib.dir/object.obj", "compiled object"),
        write_file(root / "build/.mixar-overlay-backups/existing/older.h", "older backup"),
    ]
    for path in retained:
        os.utime(path, (1_000_000_000, 1_000_000_000))
    snapshots = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in retained}
    write_file(source / shadow, "obsolete shadow header")
    write_file(source / removed, "removed overlay module")
    result = run_prune(prune_tree)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Archived 2 obsolete" in result.stdout
    assert not (source / shadow).exists()
    assert not (source / removed).exists()
    backups = [path for path in (root / "build/.mixar-overlay-backups").iterdir() if path.name != "existing"]
    assert len(backups) == 1
    assert (backups[0] / shadow).read_text() == "obsolete shadow header"
    assert (backups[0] / removed).read_text() == "removed overlay module"
    assert snapshots == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in retained}
    result = run_prune(prune_tree)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no obsolete" in result.stdout
    assert len(list((root / "build/.mixar-overlay-backups").iterdir())) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell helper")
@pytest.mark.parametrize("invalid", ["outside", "overlap", "missing_upstream"])
def test_invalid_prune_paths_refused_before_mutation(prune_tree, invalid):
    root, upstream, src, source = prune_tree
    sentinel = write_file(source / "obsolete.hh", "preserve on validation failure")
    kwargs = {}
    if invalid == "outside":
        kwargs["source"] = src
    elif invalid == "overlap":
        kwargs["upstream"] = source
    else:
        (upstream / "CMakeLists.txt").unlink()
    result = run_prune(prune_tree, **kwargs)
    assert result.returncode != 0
    assert "Overlay pruning failed" in result.stderr
    assert sentinel.read_text() == "preserve on validation failure"
    assert not (root / "build/.mixar-overlay-backups").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory junction")
def test_reparse_point_refused_before_any_orphan_move(prune_tree, tmp_path):
    root, _, _, source = prune_tree
    sentinel = write_file(source / "obsolete.hh", "preserve on validation failure")
    external = tmp_path / "outside source"
    external_file = write_file(external / "outside.hh", "untouched external file")
    junction = source / "linked directory"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(external)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_prune(prune_tree)
    assert result.returncode != 0
    assert "junction or symbolic link" in result.stderr
    assert sentinel.read_text() == "preserve on validation failure"
    assert external_file.read_text() == "untouched external file"
    assert not (root / "build/.mixar-overlay-backups").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell helper")
def test_stale_ignored_payloads_archived_but_real_git_files_preserved(prune_tree):
    root, upstream, src, source = prune_tree
    stale = ["scripts/venv/package.py", "scripts/__pycache__/old.pyc", ".DS_Store"]
    for relative in stale:
        write_file(src / relative, "excluded input must not protect shipped junk")
        write_file(source / relative, "obsolete shipped junk")
    old_python = "lib/windows_x64/python/311/bin/python.exe"
    write_file(source / old_python, "old Python dependency")
    git_file = "lib/windows_x64/.git"
    write_file(upstream / git_file, "gitdir: actual upstream library metadata")
    metadata = write_file(source / git_file, "gitdir: actual upstream library metadata")
    stdlib_venv = "lib/windows_x64/python/313/lib/venv/__init__.py"
    write_file(upstream / stdlib_venv, "legitimate bundled Python stdlib")
    bundled_venv = write_file(source / stdlib_venv, "legitimate bundled Python stdlib")
    result = run_prune(prune_tree)
    assert result.returncode == 0, result.stdout + result.stderr
    backup = next((root / "build/.mixar-overlay-backups").iterdir())
    for relative in stale + [old_python]:
        assert not (source / relative).exists()
        assert (backup / relative).is_file()
    assert metadata.read_text() == "gitdir: actual upstream library metadata"
    assert bundled_venv.read_text() == "legitimate bundled Python stdlib"


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
    generated = assembled / 'config/_build_env.py'
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text('BUILD_ENV = "Dev"\n')
    generated_stamp = generated.stat().st_mtime_ns
    windows_overlay()
    assert all(not (assembled / relative).exists() for relative in retired)
    assert not (assembled / 'modules/space_mixie_chat/ui/removed_package').exists()
    assert (assembled / live.relative_to(package)).read_bytes() == live.read_bytes()
    assert (assembled / live.relative_to(package)).stat().st_mtime_ns == timestamp
    assert (tmp_path / 'source/scripts/startup/bl_ui/stock.py').read_bytes() == stock.read_bytes()
    assert generated.read_text() == 'BUILD_ENV = "Dev"\n'
    assert generated.stat().st_mtime_ns == generated_stamp
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
