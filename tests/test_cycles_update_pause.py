# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender 5.3 removes the area-dependent pause callback and keeps a safe shim."""
import ast
from pathlib import Path
import warnings

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'intern/cycles/blender/addon/properties.py'


def source():
    overlay = ROOT / 'src' / RELATIVE
    return overlay if overlay.exists() else ROOT / 'upstream' / RELATIVE


def callback():
    path = source()
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == 'set_transform_preview_pause')
    namespace = {'warnings': warnings}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['set_transform_preview_pause']


@pytest.mark.parametrize('value', [False, True])
def test_legacy_pause_setter_needs_no_editor_context(value):
    with pytest.warns(DeprecationWarning, match='RegionView3D.pause_render'):
        assert callback()(None, value, False, True) is value


def test_legacy_pause_no_longer_registers_area_dependent_update():
    tree = ast.parse(source().read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == 'CyclesRenderSettings')
    prop = next(n for n in cls.body if isinstance(n, ast.AnnAssign)
                and n.target.id == 'preview_pause')
    keywords = {kw.arg: kw.value for kw in prop.annotation.keywords}
    assert 'update' not in keywords
    assert keywords['set_transform'].id == 'set_transform_preview_pause'


def test_obsolete_overlay_does_not_replace_cycles_53_settings():
    assert not (ROOT / 'src' / RELATIVE).exists()
