# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise the production glass fence chain with strict single-use GPU fences."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
WM = ROOT / 'src/source/blender/windowmanager'


def test_single_use_fences_preserve_cross_context_dependencies(tmp_path):
    compiler = shutil.which('cl') or shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    (tmp_path / 'BLI_assert.h').write_text('#include <cassert>\n#define BLI_assert assert\n')
    (tmp_path / 'GPU_state.hh').write_text('''#pragma once
namespace blender {
struct GPUFence;
GPUFence *GPU_fence_create();
void GPU_fence_free(GPUFence *);
void GPU_fence_signal(GPUFence *);
void GPU_fence_wait(GPUFence *);
void GPU_flush();
}
''')
    source = ROOT / 'tests/native/windows_glass_sync.cc'
    binary = tmp_path / 'glass_sync.exe'
    if Path(compiler).stem.lower() == 'cl':
        command = [compiler, '/nologo', '/EHsc', '/std:c++17',
                   f'/I{tmp_path}', f'/I{WM}', str(source), f'/Fe:{binary}']
    else:
        command = [compiler, '-std=c++17', '-I', str(tmp_path), '-I', str(WM),
                   str(source), '-o', str(binary)]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_all_shared_access_and_teardown_participate_in_the_chain():
    source = (WM / 'intern/wm_draw_mixar_glass.cc').read_text()

    def body(signature):
        start = source.index(signature)
        return source[start:source.index('\n}\n', start)]

    capture = body('void capture_host(')
    assert capture.index('glass_sync.wait();') < capture.index('release_backdrop(backdrop);')
    assert capture.index('GPU_texture_copy(') < capture.rindex('glass_sync.signal();')
    assert capture.index('GPU_scissor(scissor[0]') < capture.rindex('glass_sync.signal();')
    composite = body('void composite_backdrop(')
    assert composite.index('glass_sync.wait();') < composite.index('immBindTextureSampler(')
    assert composite.index('GPU_texture_unbind(') < composite.index('glass_sync.signal();')
    teardown = body('void wm_draw_mixar_glass_free(')
    assert teardown.index('glass_sync.wait();') < teardown.index('release_backdrop(')
    assert teardown.index('ui::mixar_glass_free();') < teardown.index('glass_sync.signal();')
    assert 'if (!host_backdrops.empty())' in teardown
    assert 'GPU_fence_' not in source
