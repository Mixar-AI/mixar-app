# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run the native view ownership contract against AppKit on macOS."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != 'darwin' or not shutil.which('clang++'),
                    reason='Requires macOS AppKit and clang++')
def test_native_glass_host_lifecycle(tmp_path):
    ghost = ROOT / 'src/intern/ghost/intern'
    executable = tmp_path / 'macos-glass-host'
    subprocess.run(['clang++', '-std=c++17', '-I', str(ghost),
                    str(ROOT / 'tests/native/macos_glass_host.mm'),
                    str(ghost / 'GHOST_MixarGlassCocoa.mm'),
                    '-framework', 'AppKit', '-framework', 'Metal',
                    '-framework', 'QuartzCore', '-o', str(executable)], check=True,
                   capture_output=True, text=True)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
