# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A finished still render is delivered from the Render Result without gating on
``has_data``: since Blender 5.3 the UI process reports it False (size 0x0) after
the render job ends, although ``save_render`` writes the render's pixels."""
import importlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def outputs(monkeypatch):
    module = importlib.import_module('mixar.modules.scene_render.core.outputs')
    fake = MagicMock()
    scene = NS(name='Scene', mixie_moodboard_images=[])
    fake.data.scenes = [scene]
    fake.context.window_manager.windows = []
    monkeypatch.setattr(module, 'bpy', fake)
    packed = []
    media = importlib.import_module('mixar.modules.moodboard.core.media_import')
    monkeypatch.setattr(media, 'pack_still_image',
                        lambda path, display_name: packed.append(Path(path).read_bytes())
                        or NS(name='Scene render'))
    utils = importlib.import_module('mixar.modules.common.utils.image_utils')
    monkeypatch.setattr(utils, 'add_image_to_moodboard', MagicMock())
    module._test_scene, module._test_packed = scene, packed
    return module


def _job(outputs, tmp_path):
    return {'scene': outputs._test_scene, 'label': '', 'kind': 'image', 'key': 'k' * 32,
            'path': str(tmp_path / 'render.png'), 'folder': str(tmp_path)}


def test_a_finished_still_is_delivered_although_has_data_says_no(outputs, tmp_path):
    outputs.bpy.data.images.get.return_value = NS(
        has_data=False, size=[0, 0],
        save_render=lambda path, scene: Path(path).write_bytes(b'png'))
    assert outputs.deliver(_job(outputs, tmp_path)) == 'Scene render'
    assert outputs._test_packed == [b'png']


def _raise(path, scene):
    raise RuntimeError(f"Image 'Render Result' does not have any image data: {path}")


@pytest.mark.parametrize('result', [
    None,
    NS(has_data=False, save_render=_raise),
    NS(has_data=False, save_render=lambda path, scene: None),
    NS(has_data=False, save_render=lambda path, scene: Path(path).write_bytes(b'')),
], ids=['missing', 'save_raises', 'no_file', 'empty_file'])
def test_a_still_without_pixels_is_output_unavailable(outputs, tmp_path, result):
    outputs.bpy.data.images.get.return_value = result
    with pytest.raises(RuntimeError, match='^output_unavailable$'):
        outputs.deliver(_job(outputs, tmp_path))
    assert outputs._test_packed == []
