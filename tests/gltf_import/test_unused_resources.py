# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real glTF/GLB parsing and importer control flow; Blender creation is stubbed."""
import ast
import importlib
import json
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / 'upstream/scripts/addons_core/io_scene_gltf2'
OVERLAY = ROOT / 'src/scripts/addons_core/io_scene_gltf2/blender/imp/blender_gltf.py'
FIXTURE = Path(__file__).with_name('fixtures') / 'triangle.gltf'


@pytest.fixture
def importer(monkeypatch):
    # Avoid the add-on registration module (requires real Blender RNA).
    package = ModuleType('_gltf_regression')
    package.__path__ = [str(UPSTREAM)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    return importlib.import_module('_gltf_regression.io.imp.gltf2_io_gltf').glTFImporter


@pytest.mark.parametrize('suffix', ['.gltf', '.glb'])
@pytest.mark.parametrize('materials,images', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('unused', [False, True])
def test_optional_resources(tmp_path, importer, suffix, materials, images, unused):
    doc = json.loads(FIXTURE.read_text())
    # Leave present resources unused, exercising creation and fake-user retention too.
    del doc['meshes'][0]['primitives'][0]['material']
    if not materials:
        del doc['materials']
    if not images:
        del doc['images']
        del doc['textures']
        if materials:
            del doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
    payload = json.dumps(doc).encode()
    if suffix == '.glb':
        payload += b' ' * (-len(payload) % 4)
        payload = struct.pack('<5I', 0x46546C67, 2, 20 + len(payload), len(payload), 0x4E4F534A) + payload
    path = tmp_path / ('triangle' + suffix)
    path.write_bytes(payload)
    gltf = importer(str(path), {'import_user_extensions': [], 'import_unused_materials': unused})
    gltf.read()
    gltf.checks()
    assert (gltf.data.materials is not None) == materials
    assert (gltf.data.images is not None) == images
    for mat in gltf.data.materials or []:
        mat.blender_material = {}
    for img in gltf.data.images or []:
        img.blender_image_name = None

    mat_id, img_id = SimpleNamespace(use_fake_user=False), SimpleNamespace(use_fake_user=False)
    def create_material(gltf, index, vertex_color):
        assert vertex_color is None
        gltf.data.materials[index].blender_material[None] = 'material'
    def create_image(gltf, index):
        gltf.data.images[index].blender_image_name = 'image'
    material = Mock(create=Mock(side_effect=create_material))
    image = Mock(create=Mock(side_effect=create_image))
    scene = Mock()
    namespace = dict(bpy=SimpleNamespace(data=SimpleNamespace(
        materials={'material': mat_id}, images={'image': img_id})),
        BlenderGlTF=Mock(), BlenderScene=scene, BlenderMaterial=material, BlenderImage=image)
    tree = ast.parse(OVERLAY.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BlenderGlTF')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_create')
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(OVERLAY), 'exec'), namespace)
    namespace['_create'](gltf)
    scene.create.assert_called_once_with(gltf)
    assert material.create.call_count == int(materials and unused)
    assert image.create.call_count == int(images and unused)
    assert mat_id.use_fake_user == (materials and unused)
    assert img_id.use_fake_user == (images and unused)
    gltf.log.flush()
