# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute the real importer function against strict current light settings.

Full binary FBX import is exercised by the companion real-app QA scenario.
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPORTER = ROOT / 'src/scripts/addons_core/io_scene_fbx/import_fbx.py'


class CyclesLightSettings:
    # RNA PropertyGroup rejects writes to removed properties.
    __slots__ = ()


def read_light(path, props):
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == 'blen_read_light')
    light = SimpleNamespace(cycles=CyclesLightSettings())
    def new(**kwargs):
        light.__dict__.update(kwargs)
        return light
    def get(_props, key, default):
        return props.get(key, default)
    ns = dict(bpy=SimpleNamespace(data=SimpleNamespace(lights=SimpleNamespace(new=new))),
              elem_name_ensure_class=lambda *_: 'FixtureLight',
              elem_find_first=lambda *_: None, fbx_elem_nil=None)
    for kind in ('enum', 'number', 'color_rgb', 'bool'):
        ns['elem_props_get_' + kind] = get
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
    return ns['blen_read_light'](None, None, SimpleNamespace(use_custom_props=False))


@pytest.mark.parametrize('kind,expected', [(0, 'POINT'), (1, 'SUN'), (2, 'SPOT')])
@pytest.mark.parametrize('shadow', [False, True])
def test_light_import_with_current_cycles_settings(kind, expected, shadow):
    light = read_light(IMPORTER, {b'LightType': kind, b'CastShadows': shadow,
                                b'Intensity': 250.0, b'Exposure': 1.0,
                                b'Color': (0.2, 0.4, 0.8),
                                b'OuterAngle': 60.0, b'InnerAngle': 30.0})
    assert light.type == expected
    assert light.use_shadow is shadow
    assert light.energy == 2.5
    assert light.exposure == 1.0
    assert light.color == (0.2, 0.4, 0.8)
    if kind == 2:
        assert light.spot_size == pytest.approx(math.pi / 3)
        assert light.spot_blend == 0.5


def test_optional_light_properties_use_defaults():
    light = read_light(IMPORTER, {})
    assert (light.type, light.energy, light.exposure, light.use_shadow) == ('POINT', 1, 0, True)
    assert light.color == (1, 1, 1)
