# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the shipped importer function with strict socket collections."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
REL = 'scripts/addons_core/io_scene_gltf2/blender/imp/pbrMetallicRoughness.py'
SOCKETS = ('Occlusion', 'Thickness', 'Dispersion',
           'Iridescence Factor', 'Iridescence Thickness Minimum')


class GroupNode:
    @property
    def inputs(self):
        return self.node_tree


def make_node(group):
    source = ROOT / 'src' / REL
    tree = ast.parse(source.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == 'make_settings_node')
    fresh = dict.fromkeys(SOCKETS, object())
    create = Mock(return_value=fresh)
    scope = {'get_settings_group': lambda: group,
             'create_settings_group': create,
             'get_gltf_node_name': lambda: 'glTF Material Output'}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
    mh = SimpleNamespace(node_tree=SimpleNamespace(
        nodes=SimpleNamespace(new=lambda kind: GroupNode())))
    return scope['make_settings_node'](mh), create, fresh


@pytest.mark.parametrize('missing', SOCKETS)
def test_incomplete_group_gets_private_compatible_replacement(missing):
    old = {name: object() for name in SOCKETS if name != missing}
    before = old.copy()
    node, create, fresh = make_node(old)
    assert node.node_tree is fresh
    assert old == before  # Existing materials and socket identities stay intact.
    create.assert_called_once_with('glTF Material Output')
    for name in SOCKETS:
        assert node.inputs[name] is not None


def test_current_group_is_reused():
    group = dict.fromkeys(SOCKETS, object())
    node, create, _ = make_node(group)
    assert node.node_tree is group
    create.assert_not_called()


def test_overlay_only_changes_settings_node():
    upstream = ROOT / 'upstream' / REL
    if not upstream.exists():
        pytest.skip('Pristine Blender checkout unavailable')
    def without_function(path):
        tree = ast.parse(path.read_text())
        tree.body = [n for n in tree.body if not (
            isinstance(n, ast.FunctionDef) and n.name == 'make_settings_node')]
        return ast.dump(tree)
    assert without_function(upstream) == without_function(ROOT / 'src' / REL)


def test_pristine_importer_reproduces_reported_keyerror():
    """The old group is accepted, then an absent optional socket is indexed."""
    upstream = ROOT / 'upstream' / REL
    if not upstream.exists():
        pytest.skip('Pristine Blender checkout unavailable')
    functions = [n for n in ast.parse(upstream.read_text()).body
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ('make_settings_node', 'pbr_metallic_roughness')]
    legacy = {'Occlusion': object(), 'Thickness': object()}
    mh = Mock()
    mh.get_ext = lambda name, default=None: default
    mh.gltf.data.extensions_used = None
    mh.pymat.occlusion_texture = object()
    # Shader sockets exist; only the legacy settings group's sockets are sparse.
    from unittest.mock import MagicMock
    mh.nodes.new = MagicMock()
    mh.node_tree.nodes.new = lambda kind: GroupNode()
    from collections import defaultdict
    scope = {'MaterialHelper': object, 'get_settings_group': lambda: legacy,
             'calc_locations': lambda mh: defaultdict(tuple)}
    for name in ('emission', 'base_color', 'metallic_roughness', 'normal',
                 'occlusion', 'clearcoat', 'transmission', 'specular',
                 'anisotropy', 'sheen', 'iridescence'):
        scope[name] = Mock()
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(upstream), 'exec'), scope)
    with pytest.raises(KeyError, match='Iridescence Factor'):
        scope['pbr_metallic_roughness'](mh)
