# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""HDRI lazy decode and transactional world replacement failures."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mixar.modules.workflow.core import zen_sky_lighting as lighting


class LazyImage:
    has_data = False

    @property
    def size(self):
        self.has_data = True
        return (8, 4)


def fixture(monkeypatch, tmp_path):
    path = tmp_path / 'sky.hdr'
    path.write_bytes(b'fixture')
    image = LazyImage()
    api = MagicMock()
    api.path.abspath.side_effect = str
    api.data.images.load.return_value = image
    monkeypatch.setattr(lighting, 'bpy', api)
    old = MagicMock()
    original = object()
    state = SimpleNamespace(sky_world=old, previous_world=original)
    scene = SimpleNamespace(world=old, mixar_zen_sky=state)
    return path, image, api, scene, original


def test_valid_lazy_image_is_decoded_before_validation_and_preserves_original(monkeypatch, tmp_path):
    path, image, api, scene, original = fixture(monkeypatch, tmp_path)
    old = scene.world
    lighting.load_hdri(scene, str(path))
    assert image.has_data
    assert scene.world is old.copy.return_value
    assert scene.mixar_zen_sky.sky_world is scene.world
    assert scene.mixar_zen_sky.previous_world is original
    api.data.images.remove.assert_not_called()


def test_node_failure_keeps_world_pointers_and_cleans_temporary_data(monkeypatch, tmp_path):
    path, image, api, scene, original = fixture(monkeypatch, tmp_path)
    old = scene.world
    replacement = old.copy.return_value
    replacement.node_tree.nodes.new.side_effect = RuntimeError('Node creation failed')
    with pytest.raises(RuntimeError, match='Node creation failed'):
        lighting.load_hdri(scene, str(path))
    assert scene.world is old and scene.mixar_zen_sky.sky_world is old
    assert scene.mixar_zen_sky.previous_world is original
    api.data.worlds.remove.assert_called_once_with(replacement)
    api.data.images.remove.assert_called_once_with(image)


def test_invalid_extension_leaves_data_untouched(monkeypatch, tmp_path):
    path, image, api, scene, original = fixture(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='hdr or .exr'):
        lighting.load_hdri(scene, str(path.with_suffix('.png')))
    api.data.images.load.assert_not_called()
