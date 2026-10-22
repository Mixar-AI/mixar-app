# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cold-process checks: checkpoint fixtures cannot export their bpy mock.

A normal pytest collection often imports Mixar before this fixture runs and
hides this leak. Use a fresh interpreter without the root conftest so all
checkpoint dependencies are first imported against the fixture's own bpy.
"""

from pathlib import Path
import subprocess
import sys

import pytest


PROBE = r'''
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType

import pytest

path, mode = Path(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location('checkpoint_fixture_probe', path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
assert not any(n == 'mixar' or n.startswith('mixar.') for n in sys.modules)

if mode == 'existing_parent':
    root = ModuleType('mixar')
    root.__path__ = [str(fixture._MIXAR_ROOT)]
    parent = ModuleType('mixar.config')
    parent.__path__ = [str(fixture._MIXAR_ROOT / 'config')]
    # The config import must restore an existing child binding as well as
    # remove brand-new bindings such as logging_config.
    original_binding = parent.config = object()
    parent.unrelated_state = 'before'
    root.config = parent
    sys.modules['mixar'] = root
    sys.modules['mixar.config'] = parent
    parent_before = vars(parent).copy()

previous = {n: m for n, m in sys.modules.items()
            if n == 'mixar' or n.startswith('mixar.')}
with tempfile.TemporaryDirectory() as temporary:
    try:
        with fixture._isolated_checkpoint_modules(), pytest.MonkeyPatch.context() as patch:
            tc = fixture._load_checkpoint_fixture(patch, Path(temporary))
            if mode == 'existing_parent':
                # This synthetic package intentionally bypassed config's
                # __init__; load its real child to exercise binding replacement.
                importlib.import_module('mixar.config.config')
            contaminated = {name for name, module in sys.modules.items()
                            if name.startswith('mixar.') and getattr(module, 'bpy', None) is tc.bpy}
            required = {'mixar.config.config', 'mixar.modules.common.utils.image_utils',
                        'mixar.modules.common.utils.mixie_space_utils'}
            assert required <= contaminated, contaminated
            if mode == 'existing_parent':
                assert parent.config is sys.modules['mixar.config.config']
                parent.unrelated_state = 'after'
            if mode == 'exception':
                raise RuntimeError('intentional fixture-body failure')
    except RuntimeError as exc:
        assert mode == 'exception' and str(exc) == 'intentional fixture-body failure', exc

current = {n: m for n, m in sys.modules.items()
           if n == 'mixar' or n.startswith('mixar.')}
assert current.keys() == previous.keys(), ('leaked modules', current.keys() - previous.keys())
assert all(current[name] is module for name, module in previous.items())
if mode == 'existing_parent':
    assert parent.config is original_binding
    assert vars(parent).keys() == parent_before.keys(), ('leaked package bindings', vars(parent))
    assert parent.unrelated_state == 'after', 'Do not rewind unrelated module state'
    assert all(vars(parent)[name] is value for name, value in parent_before.items()
               if name != 'unrelated_state')
print('PASS: cold dependency imports and parent bindings are isolated:', mode)
'''


@pytest.mark.parametrize('mode', ['cold', 'existing_parent', 'exception'])
def test_checkpoint_fixture_does_not_leak_cold_imports(mode):
    fixture = Path(__file__).with_name('conftest.py')
    result = subprocess.run(
        [sys.executable, '-c', PROBE, str(fixture), mode],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
