# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile the actual GHOST settings macros to preserve transparent windows."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_transparency_and_raytracing_flags_do_not_collide(tmp_path):
    compiler = (shutil.which('cl') if os.name == 'nt' else None)
    compiler = compiler or shutil.which('clang++') or shutil.which('g++')
    allocator = ROOT / 'upstream/intern/guardedalloc'
    if not compiler or not (allocator / 'MEM_guardedalloc.h').is_file():
        pytest.skip('requires a C++ compiler and the pinned upstream headers')
    source = ROOT / 'tests/native/ghost_context_params.cc'
    binary = tmp_path / 'context.exe'
    includes = [ROOT / 'src/intern/ghost', allocator]
    if Path(compiler).stem.lower() == 'cl':
        cmd = [compiler, '/nologo', '/EHsc', '/std:c++20',
               *(f'/I{p}' for p in includes), str(source), f'/Fe:{binary}']
    else:
        cmd = [compiler, '-std=c++20', *(f'-I{p}' for p in includes),
               str(source), '-o', str(binary)]
    subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
