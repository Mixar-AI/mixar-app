# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Movies never become Agent image payloads, including restored draft data."""

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


def test_from_blend_refuses_movie_before_adding_or_mirroring(images):
    mirror = Mock()
    namespace = dict(bpy=SimpleNamespace(data=SimpleNamespace(images=images)),
                     VIDEO_ATTACHMENT_REJECTED=VIDEO_ATTACHMENT_REJECTED,
                     mirror_attachment_to_moodboard=mirror)
    execute = function(CHAT/'ui/operators/image_ops.py', 'execute', namespace,
                       'MIXIE_CHAT_OT_add_image_from_blend')
    scene = SimpleNamespace(mixie_chat_pending_attachments=Attachments())
    op = SimpleNamespace(dropped_image_name='clip', image_name='', report=Mock())
    assert execute(op, SimpleNamespace(scene=scene)) == {'CANCELLED'}
    assert not scene.mixie_chat_pending_attachments
    mirror.assert_not_called()
    op.report.assert_called_once_with({'WARNING'}, VIDEO_ATTACHMENT_REJECTED)


def test_from_blend_picker_omits_movies():
    def image(name, source):
        return SimpleNamespace(name=name, source=source, type='IMAGE', size=(64, 64),
                               has_data=True, filepath='')
    namespace = dict(bpy=SimpleNamespace(data=SimpleNamespace(
        images=[image('clip', 'MOVIE'), image('photo', 'FILE')])) )
    get_images = function(CHAT/'core/image_utils.py', 'get_blend_images', namespace)
    assert [i['name'] for i in get_images()] == ['photo']
