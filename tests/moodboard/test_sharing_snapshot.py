# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Portable board snapshots preserve recipes without local execution state."""
import json
import io
from PIL import Image
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core import sharing_snapshot as sharing
from test_clipboard_snapshot import _Scene, _Image, _add_media, _add_node, _link


@pytest.fixture
def board(monkeypatch):
    scene = _Scene()
    scene.mixie_moodboard_frames = []
    scene.mixie_moodboard_annotations = []
    image = _Image('private-file-name.png')
    item = _add_media(scene, 'reference', image)
    item.scene_node = True
    item.scene_title = 'Study'
    item.source_scene = NS(name='Local Scene')
    monkeypatch.setattr(sharing, 'bpy', NS(data=NS(images={image.name: image})))
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buffer, 'PNG')
    monkeypatch.setattr(sharing, 'image_to_png_bytes', lambda image: buffer.getvalue())
    return scene, image


def test_snapshot_keeps_scene_preview_and_graph_without_scene_or_job_payload(board):
    scene, image = board
    node = _add_node(scene, 'generation', state='RUNNING', job_id='private-job', prompt='Moss')
    _link(scene, 'reference', node.node_id)
    payload = sharing.capture(scene)
    media = payload['snapshot']['media'][0]
    assert media['scene_title'] == 'Local Scene'
    assert media['image_name'] == 'a0'
    assert payload['snapshot']['nodes'][0]['result'] is None
    assert payload['snapshot']['links'][0]['internal'] is True
    encoded = json.dumps(payload)
    assert 'private-file-name' not in encoded and 'private-job' not in encoded
    assert 'source_scene' not in encoded
    assert scene.mixie_moodboard_images[0].selected


def test_finished_result_is_portable_and_errors_are_private(board):
    scene, image = board
    _add_node(scene, 'generated', state='SUCCESS', preview_image=image,
              job_id='private-job', error='private server details', result_names='local object')
    payload = sharing.capture(scene)
    result = payload['snapshot']['nodes'][0]['result']
    assert result['preview_image_name'] == 'a0'
    assert result['error'] == result['result_names'] == ''
    assert len(payload['assets']) == 1  # shared reference and result encoded only once


@pytest.mark.parametrize('kind', ['movie', 'mesh'])
def test_unportable_content_is_refused_before_upload(board, kind):
    scene, image = board
    if kind == 'movie':
        image.source = 'MOVIE'
    else:
        scene.mixie_moodboard_asset_nodes.add()
    with pytest.raises(ValueError):
        sharing.capture(scene)


def test_import_rejects_missing_or_duplicate_assets_before_allocation(board):
    scene, _ = board
    payload = sharing.capture(scene)
    sharing.validate_bundle(payload)
    payload['assets'] = []
    with pytest.raises(ValueError, match='missing images'):
        sharing.validate_bundle(payload)
    payload = sharing.capture(scene)
    payload['assets'] *= 2
    with pytest.raises(ValueError, match='Invalid moodboard images'):
        sharing.validate_bundle(payload)


def test_import_failure_rolls_back_new_datablocks(board, monkeypatch):
    scene, _ = board
    payload = sharing.capture(scene)
    made = NS(users=0)
    removed = []
    target = _Scene()
    monkeypatch.setattr(sharing, 'bpy', NS(data=NS(
        scenes=NS(new=lambda name: target, remove=lambda item: removed.append(item)),
        images=NS(remove=lambda item: removed.append(item)))))
    monkeypatch.setattr(sharing, 'load_image_from_base64', lambda *args: made)
    monkeypatch.setattr(sharing.clipboard, '_materialize_media', lambda *args: (_ for _ in ()).throw(ValueError('bad media')))
    with pytest.raises(ValueError, match='bad media'):
        sharing.restore(payload)
    assert removed == [target, made]


def test_pixel_budget_checked_before_encoding(board, monkeypatch):
    scene, image = board
    image.size = (9000, 9000)
    monkeypatch.setattr(sharing, 'image_to_png_bytes', lambda image: pytest.fail('must reject before encoding'))
    with pytest.raises(ValueError, match='megapixels'):
        sharing.capture(scene)
