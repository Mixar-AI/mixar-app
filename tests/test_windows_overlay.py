# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the Windows overlay after a branch removes an upstream override."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows robocopy")
def test_removed_override_restores_older_upstream_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts" / "windows"
    scripts.mkdir(parents=True)
    for name in ("overlay.bat", "settings.bat"):
        shutil.copy2(root / "scripts" / "windows" / name, scripts / name)

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
    env = dict(os.environ, MIXAR_UPSTREAM_DIR=str(tmp_path / "upstream"))

    def overlay():
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(scripts / "overlay.bat")],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    overlay()
    assert assembled.read_bytes() == override.read_bytes()
    override.unlink()  # Switching to a branch without this override.
    overlay()
    assert assembled.read_bytes() == upstream.read_bytes()
    restored_mtime = assembled.stat().st_mtime_ns
    assert restored_mtime == upstream.stat().st_mtime_ns
    overlay()
    assert assembled.stat().st_mtime_ns == restored_mtime
