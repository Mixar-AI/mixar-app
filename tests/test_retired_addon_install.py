# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise real CMake script-install rules against a dirty disposable prefix."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / 'src/source/creator/CMakeLists.txt'
RETIRED = 'addons_core/kiri_3dgs_render'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def cmake(*args, env=None):
    result = subprocess.run([shutil.which('cmake'), *map(str, args)],
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which('cmake') is None, reason='requires CMake install interpreter')
@pytest.mark.parametrize('layout,staged', [
    ('Mixar.app/Contents/Resources/5.3', False),
    ('5.3', False),  # Windows and portable Linux share this scripts layout.
    ('share/mixar/5.3', True),
    ('absolute-python-module', True),
])
def test_incremental_install_removes_retired_addon_only(tmp_path, layout, staged):
    if staged and os.name == 'nt':
        pytest.skip('CMake DESTDIR staging does not support Windows drive-letter prefixes')
    project = tmp_path / 'fixture project'
    build = tmp_path / 'configured build'
    prefix = tmp_path / 'actual install prefix'
    target = str(tmp_path / 'python site/bpy/5.3') if layout == 'absolute-python-module' else layout
    scripts = project / 'scripts'
    write(scripts / 'mixar/current.py', '# current Mixar module\n')
    write(scripts / 'addons_core/io_scene_gltf2/__init__.py', '# retained upstream addon\n')
    # Even a stale generated-source copy must not resurrect the retired addon.
    write(scripts / RETIRED / '__init__.py', '# obsolete KIRI addon\n')
    write(scripts / RETIRED / 'assets/old.blend', 'obsolete binary asset')
    write(scripts / RETIRED / '__pycache__/old.pyc', 'obsolete cache')

    creator = CREATOR.read_text()
    start = creator.index('if(WITH_PYTHON)\n', creator.index('# Install Targets (Generic, All Platforms)'))
    end = creator.index('  if(WITH_PYTHON_MODULE)\n', start)
    # Configure the actual production cleanup and DIRECTORY install rules,
    # without Blender targets, compilers, generated source or a native build.
    write(project / 'CMakeLists.txt',
          'cmake_minimum_required(VERSION 3.20)\nproject(script_install NONE)\n'
          'set(WITH_PYTHON ON)\n' + creator[start:end] + '\nendif()\n')
    cmake('-S', project, '-B', build, '-DTARGETDIR_VER=' + target,
          '-DCMAKE_INSTALL_PREFIX=' + str(tmp_path / 'unused configure prefix'))

    destination = (Path(target) if Path(target).is_absolute() else prefix / target) / 'scripts'
    env = os.environ.copy()
    env.pop('DESTDIR', None)
    if staged:
        env['DESTDIR'] = str(tmp_path / 'package stage')
        destination = Path(env['DESTDIR'] + str(destination))
    write(destination / RETIRED / '__init__.py', '# installed retired addon\n')
    write(destination / RETIRED / 'assets/old.blend', 'installed obsolete asset')
    write(destination / RETIRED / '__pycache__/old.pyc', 'installed obsolete cache')
    unrelated = write(destination / 'addons_core/unrelated_addon/__init__.py', '# keep me\n')
    user_addon = write(tmp_path / 'user-profile/scripts/addons/kiri_3dgs_render/__init__.py',
                       '# independent user installation\n')
    for _ in range(2):
        cmake('--install', build, '--prefix', prefix, env=env)
        assert not (destination / RETIRED).exists(), 'retired bundled addon survived install'
        assert (destination / 'addons_core/io_scene_gltf2/__init__.py').read_text() == '# retained upstream addon\n'
        assert (destination / 'mixar/current.py').is_file()
        assert unrelated.read_text() == '# keep me\n'
        assert user_addon.read_text() == '# independent user installation\n'
