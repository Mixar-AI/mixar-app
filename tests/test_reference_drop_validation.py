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

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / 'src/scripts/mixar/modules/space_mixie_chat'


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
    namespace = dict(os=os, MAX_ATTACHMENTS_PER_MESSAGE=5,
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


def test_webp_reference_is_supported(validate, tmp_path):
    path = tmp_path/'reference.webp'
    Image.new('RGB', (32, 32), '#abcdef').save(path)
    assert validate(str(path)) == (True, '')


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
