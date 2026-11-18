# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the production completion method and lost-session check with absent,
replaced and live sculpt state (mixar-backend#2017)."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path('source/blender/editors/sculpt_paint/mesh/sculpt.cc')


DONE = ('void SculptPaintStroke::done(', 'tests/native/sculpt_stroke_done.cc')
LOST = ('static bool stroke_lost_session(', 'tests/native/sculpt_stroke_lost_session.cc')


def program(source, target=DONE):
    signature, fixture = target
    start = source.index(signature)
    end = source.index('\n}', start) + 2
    return (ROOT / fixture).read_text().replace('// PRODUCTION_FUNCTION', source[start:end])


def compile_program(source, folder, target=DONE):
    compiler = (shutil.which('cl') if os.name == 'nt' else None)
    compiler = compiler or shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler required')
    cpp = folder / 'stroke.cc'
    cpp.write_text(program(source, target))
    binary = folder / ('stroke.exe' if os.name == 'nt' else 'stroke')
    if Path(compiler).stem.lower() == 'cl':
        cmd = [compiler, '/nologo', '/EHsc', '/std:c++17', str(cpp), '/Fe:' + str(binary)]
    else:
        cmd = [compiler, '-std=c++17', str(cpp), '-o', str(binary)]
    proc = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return binary


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    return compile_program((ROOT / 'src' / RELATIVE).read_text(),
                           tmp_path_factory.mktemp('sculpt-done'))


@pytest.mark.parametrize('case', ['missing', 'missing_cancel', 'empty', 'normal',
                                 'cancel', 'unstarted', 'smooth', 'mask'])
def test_completion_preserves_cleanup_without_dereferencing_missing_session(binary, case):
    proc = subprocess.run([str(binary), case], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.fixture(scope='module')
def lost_binary(tmp_path_factory):
    return compile_program((ROOT / 'src' / RELATIVE).read_text(),
                           tmp_path_factory.mktemp('sculpt-lost'), LOST)


@pytest.mark.parametrize('case, verdict', [
    ('missing', 'lost'),
    ('object_mode', 'lost'),
    ('texture_paint', 'lost'),
    ('vertex_paint', 'lost'),
    ('weight_paint', 'lost'),
    ('round_trip', 'lost'),
    ('round_trip_unstarted', 'lost'),
    ('other_cache', 'lost'),
    ('same', 'kept'),
    ('unstarted', 'kept'),
])
def test_lost_session_only_flags_a_session_that_is_not_the_strokes(lost_binary, case, verdict):
    proc = subprocess.run([str(lost_binary), case], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == verdict
