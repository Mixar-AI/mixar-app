# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the exporter's custom-property writer with the real binary encoder,
without Blender (mixar-backend#2003)."""
import ast
import importlib.util
import os
from pathlib import Path
import re
import struct
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
FBX_DIR = 'scripts/addons_core/io_scene_fbx'
EXPORTER = ROOT / 'src' / FBX_DIR / 'export_fbx_bin.py'
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; use MIXAR_UPSTREAM_DIR if set, else this checkout's `upstream/`, else the
# main checkout's two levels up (ROOT.parents[1] / 'upstream').
UPSTREAM_ROOTS = (os.environ.get('MIXAR_UPSTREAM_DIR'), ROOT / 'upstream', ROOT.parents[1] / 'upstream')
UPSTREAM = next((Path(base) / FBX_DIR for base in UPSTREAM_ROOTS
                 if base and (Path(base) / FBX_DIR / 'encode_bin.py').exists()), None)
ORIGINAL_CALL = 'elem_props_set(props, "p_vector", k.encode(), list_val, custom=True)'
# The overlay's fix: a comment line, then the call with float components.
FIX = re.compile(r' *#[^\n]*\n( *elem_props_set\(props, "p_vector", k\.encode\(\), )'
                 r'\[float\((\w+)\) for \2 in list_val\]')


@pytest.fixture
def upstream():
    if UPSTREAM is None:
        pytest.skip("upstream submodule not checked out")
    return UPSTREAM


def functions(path, names, ns):
    nodes = [n for n in ast.parse(path.read_text(encoding='utf-8')).body
             if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign) and any(
                 isinstance(t, ast.Name) and t.id in names for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)


@pytest.fixture
def exporter(monkeypatch, upstream):
    package = ModuleType('_test_fbx_binary')
    package.__path__ = [str(upstream)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    name = package.__name__ + '.encode_bin'
    spec = importlib.util.spec_from_file_location(name, upstream / 'encode_bin.py')
    encoder = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, encoder)
    spec.loader.exec_module(encoder)
    ns = {'encode_bin': encoder}
    functions(upstream / 'fbx_utils.py', {
        'FBX_PROPERTIES_DEFINITIONS', 'elem_empty', '_elem_data_single',
        'elem_data_single_string', '_elem_props_set', '_elem_props_flags',
        'elem_props_set'}, ns)
    functions(EXPORTER, {'fbx_data_element_custom_properties'}, ns)
    return encoder, ns


class Array:
    def __init__(self, values):
        self.values = values

    def to_list(self):
        return self.values


class Properties(dict):
    bl_rna = SimpleNamespace(properties=[])


@pytest.mark.parametrize('values, doubles', [
    ([1, -2, 3], [1.0, -2.0, 3.0]),
    ([True, False, True], [1.0, 0.0, 1.0]),
    ([1.25, -2.5, 3.75], [1.25, -2.5, 3.75]),
    ([0, 0, 0], [0.0, 0.0, 0.0]),
])
def test_custom_vectors_are_binary_doubles(exporter, values, doubles):
    encoder, ns = exporter
    root = encoder.FBXElem(b'Properties70')
    ns['fbx_data_element_custom_properties'](root, Properties(vector=Array(values)))
    prop, = root.elems
    assert prop.props_type == bytearray(b'SSSSDDD')
    assert prop.props[1][4:] == b'Vector'
    assert [struct.unpack('<d', v)[0] for v in prop.props[4:]] == doubles


def test_scalar_and_non_vector_properties_keep_their_types(exporter):
    encoder, ns = exporter
    root = encoder.FBXElem(b'Properties70')
    ns['fbx_data_element_custom_properties'](
        root, Properties(integer=7, scalar=1.25, text='hello', pair=Array([1, 2])))
    assert [bytes(p.props_type) for p in root.elems] == [b'SSSSI', b'SSSSD', b'SSSSS', b'SSSSS']
    assert struct.unpack('<i', root.elems[0].props[-1])[0] == 7
    assert struct.unpack('<d', root.elems[1].props[-1])[0] == 1.25
    assert root.elems[3].props[-1][4:] == b'[1, 2]'


def test_overlay_is_upstream_plus_the_vector_fix(upstream):
    original = (upstream / 'export_fbx_bin.py').read_text(encoding='utf-8')
    assert ORIGINAL_CALL in original, (
        "upstream's export_fbx_bin.py no longer writes the raw list; if it now converts "
        f"the vector components to float, delete the overlay {EXPORTER.relative_to(ROOT)}")
    unfixed, count = FIX.subn(r'\1list_val', EXPORTER.read_text(encoding='utf-8'))
    assert count == 1, "the overlay's float conversion of custom vectors is missing"
    assert unfixed == original, (
        "the overlay must be the pinned upstream file plus the vector fix only; "
        "re-copy upstream's file and reapply the fix")
