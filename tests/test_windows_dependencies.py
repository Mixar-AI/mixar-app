# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the read-only Windows preflight against disposable dependency trees."""

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell helper")
HELPER = Path(__file__).resolve().parents[1] / "scripts/windows/check_dependencies.ps1"


def git(directory, *args):
    result = subprocess.run(
        ["git", "-C", str(directory), *args], check=True,
        capture_output=True, text=True,
        env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                 GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                 GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid"),
    )
    return result.stdout.strip()


def commit(directory):
    git(directory, "add", "--all")
    git(directory, "commit", "--allow-empty", "-m", "fixture")
    return git(directory, "rev-parse", "HEAD")


def payload(upstream):
    python = upstream / "lib/windows_x64/python/313"
    for folder in ("bin", "include", "libs"):
        (python / folder).mkdir(parents=True, exist_ok=True)
    executable = bytearray(128)
    executable[:2] = b"MZ"
    struct.pack_into("<I", executable, 60, 64)
    struct.pack_into("<IH", executable, 64, 0x4550, 0x8664)
    (python / "bin/python.exe").write_bytes(executable)
    (python / "include/Python.h").write_text("/* Python C API */\n")
    (python / "libs/python313.lib").write_bytes(b"!<arch>\nimport library")
    return python


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "project with spaces"
    upstream = root / "upstream"
    lib = upstream / "lib/windows_x64"
    lib.mkdir(parents=True)
    for directory in (root, upstream, lib):
        git(directory, "init", "--quiet")
        git(directory, "config", "core.autocrlf", "false")
    python = payload(upstream)
    lib_sha = commit(lib)
    git(upstream, "update-index", "--add", "--cacheinfo", f"160000,{lib_sha},lib/windows_x64")
    upstream_sha = commit(upstream)
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{upstream_sha},upstream")
    commit(root)
    helper = tmp_path / "helper with spaces" / HELPER.name
    helper.parent.mkdir()
    shutil.copy2(HELPER, helper)
    return root, upstream, lib, python, helper


def run(tree, upstream=None):
    root, selected, _, _, helper = tree
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(helper), "-RootDir", str(root),
         "-UpstreamDir", str(upstream or selected), "-PythonVersion", "3.13"],
        capture_output=True, text=True,
    )


def output(result):
    return result.stdout + result.stderr


def test_matching_pins_pass_without_mutation(tree):
    snapshots = [(path, path.read_bytes()) for path in tree[0].rglob("*") if path.is_file()]
    result = run(tree)
    assert result.returncode == 0, output(result)
    assert "Python 3.13" in output(result)
    assert all(path.read_bytes() == before for path, before in snapshots)


@pytest.mark.parametrize("index, message", [(1, "Upstream revision mismatch"),
                                           (2, "Windows library revision mismatch")])
def test_stale_pin_is_actionable_and_unchanged(tree, index, message):
    wrong_sha = commit(tree[index])
    result = run(tree)
    assert result.returncode != 0
    assert message in output(result)
    assert "checkout --detach" in output(result)
    assert git(tree[index], "rev-parse", "HEAD") == wrong_sha


def test_uninitialized_nested_repo_does_not_use_parent_head(tree):
    (tree[2] / ".git").rename(tree[2] / "saved-git-metadata")
    result = run(tree)
    assert result.returncode != 0
    assert "Windows libraries are not initialized" in output(result)
    assert "submodule update --init --checkout lib/windows_x64" in output(result)


@pytest.mark.parametrize("relative", ["bin/python.exe", "include/Python.h", "libs/python313.lib"])
def test_lfs_pointer_rejected_early(tree, relative):
    (tree[3] / relative).write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
    result = run(tree)
    assert result.returncode != 0
    assert "Git LFS pointer" in output(result)
    assert "lfs pull" in output(result)


@pytest.mark.parametrize("relative", ["bin/python.exe", "include/Python.h", "libs/python313.lib"])
def test_missing_python_payload_rejected(tree, relative):
    (tree[3] / relative).unlink()
    result = run(tree)
    assert result.returncode != 0
    assert "Missing dependency" in output(result)


def test_wrong_machine_executable_rejected(tree):
    exe = tree[3] / "bin/python.exe"
    data = bytearray(exe.read_bytes())
    struct.pack_into("<H", data, 68, 0xaa64)  # ARM64 cannot satisfy this x64 build.
    exe.write_bytes(data)
    result = run(tree)
    assert result.returncode != 0
    assert "Windows x64 PE executable" in output(result)


def test_source_archive_checks_payload_without_git_pin(tree):
    (tree[0] / ".git").rename(tree[0] / "saved-git-metadata")
    result = run(tree)
    assert result.returncode == 0, output(result)
    assert "Source archive" in output(result)


def test_selected_external_upstream_is_supported(tree, tmp_path):
    external = tmp_path / "shared upstream with spaces"
    shutil.move(str(tree[1]), external)
    result = run(tree, upstream=external)
    assert result.returncode == 0, output(result)
