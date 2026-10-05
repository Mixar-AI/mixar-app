# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise scoped CMake metadata backups using the real PowerShell helper."""

from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell helper")
HELPER = Path(__file__).resolve().parents[1] / "scripts/windows/prepare_toolchain.ps1"


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "project with spaces"
    build = root / "build" / "Dev"
    compiler = write(tmp_path / "VS tools" / "cl.exe", "selected compiler")
    version = build / "CMakeFiles" / "3.24.3"
    cache = write(build / "CMakeCache.txt",
                  f"CMAKE_C_COMPILER:FILEPATH={compiler.as_posix()}\n"
                  f"CMAKE_CXX_COMPILER:FILEPATH={compiler.as_posix()}\nKEEP:STRING=choice\n")
    for language in ("C", "CXX"):
        write(version / f"CMake{language}Compiler.cmake",
              f'set(CMAKE_{language}_COMPILER "{compiler.as_posix()}")\n')
    objects = [
        write(build / "CMakeFiles" / "main.dir" / "a.obj", "root target object"),
        write(build / "source" / "CMakeFiles" / "lib.dir" / "b.obj", "nested target object"),
        write(root / "source" / "CMakeLists.txt", "source stays unchanged"),
        write(build / ".ninja_log", "existing Ninja command history"),
    ]
    return root, build, compiler, cache, version, objects


def run(tree, build=None):
    root, selected_build, compiler, *_ = tree
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(HELPER), "-RootDir", str(root), "-BuildDir", str(build or selected_build),
         "-Compiler", str(compiler)], capture_output=True, text=True,
    )


def assert_ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def test_matching_toolchain_is_exact_noop(tree):
    snapshots = {path: path.read_bytes() for path in tree[0].rglob("*") if path.is_file()}
    assert_ok(run(tree))
    assert not (tree[1] / ".mixar-toolchain-backups").exists()
    assert snapshots == {path: path.read_bytes() for path in tree[0].rglob("*") if path.is_file()}


def test_cache_mismatch_backs_up_only_configuration_and_preserves_objects(tree):
    root, build, _, cache, version, objects = tree
    cache.write_text("CMAKE_C_COMPILER:FILEPATH=C:/old tools/cl.exe\nKEEP:STRING=choice\n")
    original_cache = cache.read_bytes()
    original_objects = {path: path.read_bytes() for path in objects}
    old_backup = write(build / ".mixar-toolchain-backups" / "existing" / "CMakeCache.txt", "older backup")
    result = run(tree)
    assert_ok(result)
    assert "Manual CMake-only options will reset" in result.stdout
    backups = [path for path in old_backup.parent.parent.iterdir() if path.name != "existing"]
    assert len(backups) == 1
    assert (backups[0] / "CMakeCache.txt").read_bytes() == original_cache
    assert (backups[0] / "CMakeFiles" / "3.24.3" / "CMakeCCompiler.cmake").exists()
    assert not cache.exists() and not version.exists()
    assert old_backup.read_text() == "older backup"
    assert all(path.read_bytes() == value for path, value in original_objects.items())
    assert_ok(run(tree))  # A retry before configure creates no extra backup.
    assert len(list(old_backup.parent.parent.iterdir())) == 2


@pytest.mark.parametrize("language", ["C", "CXX"])
def test_metadata_only_mismatch_is_not_hidden_by_matching_cache(tree, language):
    info = tree[4] / f"CMake{language}Compiler.cmake"
    info.write_text(f'set(CMAKE_{language}_COMPILER "C:/old tools/cl.exe")\n')
    assert_ok(run(tree))
    assert not tree[3].exists()
    assert not tree[4].exists()


@pytest.mark.parametrize("relative", ["outside", "build", "build-other/Dev", "build/../source"])
def test_outside_build_directory_is_refused_before_mutation(tree, relative):
    target = tree[0] / relative
    sentinel = write(target / "CMakeCache.txt", "do not move")
    result = run(tree, build=target)
    assert result.returncode != 0
    assert "Refusing path outside" in result.stderr
    assert sentinel.read_text() == "do not move"
    assert not (target / ".mixar-toolchain-backups").exists()


def test_separate_switches_keep_unique_backups(tree):
    tree[3].write_text("CMAKE_CXX_COMPILER:FILEPATH=C:/old/cl.exe\n")
    assert_ok(run(tree))
    tree[3].write_text("CMAKE_CXX_COMPILER:FILEPATH=C:/another/cl.exe\n")
    assert_ok(run(tree))
    backups = list((tree[1] / ".mixar-toolchain-backups").iterdir())
    assert len(backups) == 2
    assert {path.joinpath("CMakeCache.txt").read_text() for path in backups} == {
        "CMAKE_CXX_COMPILER:FILEPATH=C:/old/cl.exe\n",
        "CMAKE_CXX_COMPILER:FILEPATH=C:/another/cl.exe\n",
    }


def test_path_separator_and_case_normalization_does_not_reset(tree):
    compiler = str(tree[2]).upper()
    tree[3].write_text(f"CMAKE_C_COMPILER:FILEPATH={compiler}\n")
    assert_ok(run(tree))
    assert tree[3].exists()


def test_missing_build_directory_is_safe_first_configuration(tree):
    assert_ok(run(tree, build=tree[0] / "build" / "New"))
    assert not (tree[0] / "build" / "New").exists()
