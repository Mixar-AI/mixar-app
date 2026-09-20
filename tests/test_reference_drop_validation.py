# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Execute the real operator body under bpy's mock; reject before mutation."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

from mixar.modules.space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / 'src/scripts/mixar/modules/space_mixie_chat'
VIDEO_MESSAGE = "Videos can't be sent to the agent yet"


class Attachments(list):
    def add(self):
        item = SimpleNamespace()
        self.append(item)
        return item


def function(path, name, namespace, owner=None):
    tree = ast.parse(path.read_text())
    body = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner).body if owner else tree.body
    node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def execute(paths, *, attachments=None, valid=None, model=False):
    attachments = attachments if attachments is not None else Attachments()
    mirror = Mock()
    importer = Mock(return_value={'success': True, 'display_name': 'model.obj',
                                  'imported_object_names': ['Object']})
    namespace = dict(os=os, MAX_ATTACHMENTS_PER_MESSAGE=MAX_ATTACHMENTS_PER_MESSAGE,
                     is_model_file=lambda p: model, import_model_attachment=importer,
                     validate_image_file=valid or (lambda p: (False, 'Cannot decode image')),
                     find_attachment_for_file=lambda a, p: None,
                     get_image_display_name=lambda p, s: Path(p).name,
                     mirror_attachment_to_moodboard=mirror,
                     redraw_chat_areas=Mock(), sync_bubble_attachment_size_deferred=Mock())
    fn = function(CHAT/'ui/operators/image_ops.py', 'execute', namespace,
                  'MIXIE_CHAT_OT_add_image_from_file')
    op = SimpleNamespace(files=[SimpleNamespace(name=p) for p in paths], directory='',
                         filepath='', report=Mock())
    context = SimpleNamespace(scene=SimpleNamespace(mixie_chat_pending_attachments=attachments),
                              screen=SimpleNamespace(areas=[]))
    result = fn(op, context)
    return result, attachments, mirror, importer, op.report


def test_invalid_reference_never_adds_a_pill_or_board_item():
    result, attachments, mirror, _, report = execute(['/tmp/broken.png'])
    assert result == {'CANCELLED'} and not attachments
    mirror.assert_not_called()
    assert 'Cannot decode image' in report.call_args.args[1]


def test_batch_keeps_valid_siblings_after_a_rejected_file():
    result, attachments, mirror, _, _ = execute(
        ['broken.png', 'good.png'], valid=lambda p: (p == 'good.png', 'Cannot decode image'))
    assert result == {'FINISHED'}
    assert [a.image_path for a in attachments] == ['good.png']
    mirror.assert_called_once()


def test_repeated_model_reference_does_not_import_duplicate_scene_objects():
    attachments = Attachments([SimpleNamespace(image_path='/tmp/model.obj', image_source='MODEL_FILE')])
    _, attachments, _, importer, _ = execute(['/tmp/model.obj'], attachments=attachments, model=True)
    importer.assert_not_called()
    assert len(attachments) == 1


@pytest.fixture
def validate():
    namespace = dict(os=os, HAS_PIL=True, PILImage=Image, MAX_IMAGE_DIMENSION=16384,
                     MAX_IMAGE_SIZE_BYTES=25*1024*1024,
                     SUPPORTED_IMAGE_FORMATS={'.png', '.jpg', '.webp'},
                     VIDEO_FILE_FORMATS={'.mp4', '.mov', '.webm'},
                     VIDEO_ATTACHMENT_REJECTED=VIDEO_MESSAGE,
                     _is_path_safe=lambda p: (True, ''))
    return function(CHAT/'core/image_utils.py', 'validate_image_file', namespace)


def test_corrupt_image_and_directory_report_validation_errors(validate, tmp_path):
    broken = tmp_path/'broken.png'
    broken.write_bytes(b'not an image')
    assert not validate(str(broken))[0]
    assert not validate(str(tmp_path))[0]


def test_truncated_png_is_rejected_after_its_valid_header(validate, tmp_path):
    path = tmp_path/'truncated.png'
    Image.new('RGB', (128, 128), '#123456').save(path)
    path.write_bytes(path.read_bytes()[:55])
    assert not validate(str(path))[0]


def _flip_png_chunk_crc(data: bytearray, chunk: bytes = b'IDAT') -> bytearray:
    """Corrupt one PNG chunk CRC without truncating the file."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], 'big')
        crc_off = offset + 8 + length
        if bytes(data[offset + 4:offset + 8]) == chunk:
            data[crc_off] ^= 0xFF
            return data
        offset = crc_off + 4
    raise AssertionError(f'PNG has no {chunk!r} chunk')


def test_validate_image_file_catches_pillow_crc_syntax_error():
    src = (CHAT / 'core/image_utils.py').read_text()
    start = src.index('def validate_image_file')
    body = src[start:src.index('\ndef ', start + 1)]
    assert 'SyntaxError' in body
    assert 'img.verify()' in body


def test_crc_corrupt_png_is_rejected_without_raising(validate, tmp_path):
    """Pillow's PNG CRC check raises SyntaxError, not OSError.

    A truncated file is already covered above. Image.open() still reads
    an IDAT-CRC-corrupt PNG (header is intact); img.verify() then raises
    SyntaxError. The validator must return (False, message) so a
    multi-file attach rejects only that file.
    """
    path = tmp_path / 'crc_corrupt.png'
    Image.new('RGB', (32, 32), '#123456').save(path)
    path.write_bytes(_flip_png_chunk_crc(bytearray(path.read_bytes())))
    valid, err = validate(str(path))
    assert valid is False
    assert 'Could not read image' in err


def test_webp_reference_is_supported(validate, tmp_path):
    path = tmp_path/'reference.webp'
    Image.new('RGB', (32, 32), '#abcdef').save(path)
    assert validate(str(path)) == (True, '')


@pytest.mark.parametrize('name', ['clip.mp4', 'clip.MOV', 'clip.webm'])
def test_video_reference_is_refused_with_a_specific_reason(validate, tmp_path, name):
    path = tmp_path/name
    path.write_bytes(b'\x00\x00\x00\x18ftypmp42')
    valid, err = validate(str(path))
    assert valid is False
    assert err == VIDEO_MESSAGE
    assert 'Unsupported format' not in err


def test_chat_drop_poll_refuses_movie_paths_before_release():
    src = (ROOT/'src/source/blender/editors/space_mixie_chat/mixie_chat_dragdrop.cc').read_text()
    start = src.index('if (drag->type == WM_DRAG_PATH)')
    body = src[start:src.index('return false;\n}', start)]
    assert 'WM_drag_has_path_file_type(drag, FILE_TYPE_MOVIE)' in body
    assert body.index('FILE_TYPE_MOVIE') < body.index('return true;')


def test_moodboard_attach_reports_skipped_videos():
    src = ROOT/'src/scripts/mixar/modules/moodboard/ui/operators/chat_integration_ops.py'
    namespace = dict(is_video_item=lambda item: item.video)
    count = function(src, 'count_selected_videos', namespace)
    still = SimpleNamespace(selected=True, video=False)
    clip = SimpleNamespace(selected=True, video=True)
    idle = SimpleNamespace(selected=False, video=True)
    assert count(SimpleNamespace(mixie_moodboard_images=[still, clip, idle, clip])) == 2
    body = src.read_text()
    execute = body[body.index('class MIXIE_OT_moodboard_send_to_chat'):]
    assert 'count_selected_videos(scene)' in execute
    assert "'WARNING'" in execute[execute.index('skipped_videos'):]


@pytest.mark.parametrize('target,remaining', [('/tmp/b.obj', ['/tmp/a.obj']),
                                            ('/tmp/gone.obj', ['/tmp/a.obj', '/tmp/b.obj'])])
def test_preview_remove_resolves_identity_after_collection_changes(target, remaining):
    class IndexedAttachments(list):
        def remove(self, index):
            del self[index]
    items = IndexedAttachments(SimpleNamespace(image_path=p, image_source='MODEL_FILE', display_name=p)
                               for p in ('/tmp/a.obj', '/tmp/b.obj'))
    namespace = dict(redraw_chat_areas=Mock(), cleanup_loaded_file_image=Mock())
    fn = function(CHAT/'ui/operators/image_ops.py', 'execute', namespace,
                  'MIXIE_CHAT_OT_remove_attachment')
    op = SimpleNamespace(index=0, attachment_path=target, attachment_source='MODEL_FILE', report=Mock())
    fn(op, SimpleNamespace(scene=SimpleNamespace(mixie_chat_pending_attachments=items)))
    assert [item.image_path for item in items] == remaining
