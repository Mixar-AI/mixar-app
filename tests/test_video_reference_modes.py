# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Movies never become Agent image payloads, including restored draft data;
new entry points route them to context-file chips instead."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.space_mixie_chat.core import attachment_validation as validation
from mixar.modules.space_mixie_chat.core import composer_send, image_utils
from mixar.modules.space_mixie_chat.constants import VIDEO_ATTACHMENT_REJECTED
from test_reference_drop_validation import Attachments, CHAT, function


@pytest.fixture
def images(monkeypatch):
    images = {'clip': SimpleNamespace(source='MOVIE', has_data=True),
              'photo': SimpleNamespace(source='FILE', has_data=True)}
    fake_bpy = SimpleNamespace(data=SimpleNamespace(images=images))
    monkeypatch.setattr(validation, 'bpy', fake_bpy)
    return images


@pytest.mark.parametrize('path,source,video', [
    ('/tmp/clip.MP4', 'FILE', True), ('/tmp/clip.mov', 'FILE', True),
    ('/tmp/clip.WMV', 'FILE', True), ('/tmp/clip.vob', 'FILE', True),
    ('/tmp/photo.png', 'FILE', False), ('clip', 'BLEND_DATA', True),
    ('photo', 'BLEND_DATA', False), ('missing', 'BLEND_DATA', False),
    ('/tmp/model.obj', 'MODEL_FILE', False),
])
def test_reference_kind(images, path, source, video):
    assert validation.is_video_attachment(path, source) is video


@pytest.mark.parametrize('path,source', [('clip', 'BLEND_DATA'), ('clip.mp4', 'FILE')])
def test_send_refuses_restored_video_before_session_or_transport(images, monkeypatch, path, source):
    scene = SimpleNamespace(mixie_chat_input='Keep this draft',
                            mixie_chat_pending_attachments=[
                                SimpleNamespace(image_path=path, image_source=source)])
    monkeypatch.setattr(composer_send, 'get_session_manager',
                        lambda: pytest.fail('Video crossed the send guard'))
    assert composer_send.can_send(scene) == (False, VIDEO_ATTACHMENT_REJECTED)
    assert scene.mixie_chat_input == 'Keep this draft'
    assert len(scene.mixie_chat_pending_attachments) == 1


@pytest.mark.parametrize('path,source', [('clip', 'BLEND_DATA'), ('clip.mp4', 'FILE')])
def test_encoder_cannot_turn_video_into_a_still_or_raw_image_payload(images, monkeypatch, path, source):
    from mixar.modules.space_mixie_chat.core import attachment_compression as compression
    for name in ('compress_file_for_chat', 'compress_blend_image_for_chat'):
        monkeypatch.setattr(compression, name,
                            lambda *a: pytest.fail('Video reached image compression'))
    assert image_utils.encode_attachment_for_upload(path, source) is None


def test_from_blend_routes_a_movie_to_a_context_file(tmp_path):
    # Retargeted: a MOVIE datablock is no longer refused — its file becomes a
    # context-file chip (attach_file); still no pill and no board mirror.
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'\x00\x00\x00\x18ftypmp42')
    images = {'clip': SimpleNamespace(source='MOVIE', has_data=True, filepath=str(clip))}
    mirror, attach = Mock(), Mock(return_value={'success': True, 'file_id': 'f', 'name': 'clip.mp4',
                                                'kind': 'video', 'already': False})
    namespace = dict(os=os, rpt_=lambda s: s,
                     bpy=SimpleNamespace(data=SimpleNamespace(images=images),
                                         path=SimpleNamespace(abspath=lambda p: p)),
                     attach_file=attach, mirror_attachment_to_moodboard=mirror,
                     redraw_chat_areas=Mock(), sync_bubble_attachment_size_deferred=Mock())
    execute = function(CHAT/'ui/operators/image_ops.py', 'execute', namespace,
                       'MIXIE_CHAT_OT_add_image_from_blend')
    scene = SimpleNamespace(mixie_chat_pending_attachments=Attachments())
    op = SimpleNamespace(dropped_image_name='clip', image_name='', report=Mock())
    assert execute(op, SimpleNamespace(scene=scene)) == {'FINISHED'}
    assert not scene.mixie_chat_pending_attachments
    mirror.assert_not_called()
    attach.assert_called_once_with(scene, os.path.realpath(str(clip)), origin='blend')
    # A movie whose file vanished is an error, not a silent no-op.
    images['clip'].filepath = str(tmp_path / 'gone.mp4')
    attach.reset_mock()
    assert execute(op, SimpleNamespace(scene=scene)) == {'CANCELLED'}
    attach.assert_not_called()
    assert op.report.call_args.args[0] == {'ERROR'}


def test_from_blend_picker_includes_movies():
    # Retargeted: movies are listed (flagged is_movie) so the picker can
    # attach one as a context file.
    def image(name, source):
        return SimpleNamespace(name=name, source=source, type='IMAGE', size=(64, 64),
                               has_data=True, filepath='')
    namespace = dict(bpy=SimpleNamespace(data=SimpleNamespace(
        images=[image('clip', 'MOVIE'), image('photo', 'FILE')])) )
    get_images = function(CHAT/'core/image_utils.py', 'get_blend_images', namespace)
    assert [(i['name'], i['is_movie']) for i in get_images()] == [('clip', True), ('photo', False)]
