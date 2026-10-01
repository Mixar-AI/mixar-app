# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute production window matching with inaccessible outgoing screens.

The native fixture supplies only Blender's surrounding infrastructure. The
classification, snapshot, matching and fallback functions are extracted from
wm_files.cc, so restoring a post-Main-free screen lookup fails this test.
"""

from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
WM_FILES = ROOT / 'src/source/blender/windowmanager/intern/wm_files.cc'
FIXTURE = ROOT / 'tests/native/file_read_window_lifetime.cc'


def _definition(source, signature):
    start = source.index(signature)
    end = source.index('\n}', start) + 2
    return source[start:end]


def _program(source):
    definitions = [
        _definition(source, 'struct wmFileReadWMSetupData') + ';',
        _definition(source, 'static bool wm_window_contains_agent_bubble_space('),
        _definition(source, 'static wmFileReadWMSetupData *wm_file_read_setup_wm_init('),
        _definition(source, 'static void wm_file_read_setup_wm_use_new('),
    ]
    return FIXTURE.read_text(encoding='utf-8').replace(
        '// PRODUCTION_FUNCTIONS', '\n\n'.join(definitions))


@pytest.fixture(scope='module')
def window_matching_binary(tmp_path_factory):
    compiler = (shutil.which('cl') if os.name == 'nt' else None)
    compiler = compiler or shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        pytest.skip('C++ compiler required (on Windows, use a VS developer shell)')
    folder = tmp_path_factory.mktemp('window-lifetime')
    source = folder / 'window_lifetime.cc'
    source.write_text(_program(WM_FILES.read_text(encoding='utf-8')), encoding='utf-8')
    binary = folder / ('window_lifetime.exe' if os.name == 'nt' else 'window_lifetime')
    if Path(compiler).stem.lower() == 'cl':
        command = [compiler, '/nologo', '/EHsc', '/std:c++20', '/utf-8',
                   str(source), '/Fe:' + str(binary)]
    else:
        command = [compiler, '-std=c++20', str(source), '-o', str(binary)]
    completed = subprocess.run(command, cwd=folder, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return binary


@pytest.mark.parametrize('scenario', ['matching', 'fallback', 'ordinary', 'empty'])
def test_old_screens_are_never_read_after_main_replacement(window_matching_binary, scenario):
    completed = subprocess.run([str(window_matching_binary), scenario],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_snapshot_is_owned_and_destroyed_by_each_file_read():
    source = WM_FILES.read_text(encoding='utf-8')
    init = _definition(source, 'static wmFileReadWMSetupData *wm_file_read_setup_wm_init(')
    assert init.index('old_agent_bubble_windows.add') < init.index('ED_screen_exit(')
    finalize = _definition(source, 'static void wm_file_read_setup_wm_finalize(')
    assert 'wmFileReadWMSetupData *wm_setup_data' in finalize
    assert 'MEM_delete(wm_setup_data)' in finalize
    # Both Open and New/Recover must retain the derived owner through finalization.
    assert 'BlendFileReadWMSetupData *wm_setup_data = wm_file_read_setup_wm_init' not in source
    assert 'BlendFileReadWMSetupData *wm_setup_data = nullptr' not in source
