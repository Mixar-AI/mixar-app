# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A picture is attached once, however it got into the composer.

Dropping an image into the chat stores a FILE attachment and mirrors the file
onto the moodboard as a packed datablock that keeps its ``filepath``. Selecting
that board item used to make the board→composer sync add a second,
moodboard-flagged pill, because it only de-duped against BLEND_DATA names.
These tests pin the shared identity rules (``chat_sync_dedupe``) on both
sides of the sync and on the composer's own attach/remove operators.

``bpy`` is a MagicMock here, so ``bpy.path.abspath`` hands back a mock and the
helpers fall through to the raw path — which is what lets them run at all.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import bpy
import pytest

from mixar.modules.moodboard.core import chat_sync
from mixar.modules.moodboard.core import chat_sync_dedupe as dedupe

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
IMAGE_OPS = CHAT / "ui/operators/image_ops.py"
CHAT_SYNC = ROOT / "src/scripts/mixar/modules/moodboard/core/chat_sync.py"
CHAT_SYNC_DESELECT = ROOT / "src/scripts/mixar/modules/moodboard/core/chat_sync_deselect.py"


def _load_board_sync():
    """Load by path: importing through ``space_mixie_chat.core`` pulls in the
    auth module and its native keyring dependency."""
    import importlib.util

    path = CHAT / "core/attachment_board_sync.py"
    spec = importlib.util.spec_from_file_location("attachment_board_sync_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


attachment_board_sync = _load_board_sync()

PHOTO = "/tmp/mixar-tests/photo.png"
OTHER = "/tmp/mixar-tests/other.png"


# ----------------------------------------------------------------- #
# Fakes
# ----------------------------------------------------------------- #
class FakeAttachments(list):
    """Enough of ``bpy_prop_collection`` for the sync: add()/remove(i)."""

    def add(self):
        att = SimpleNamespace(
            image_path="", image_source='FILE', display_name="", is_moodboard=False
        )
        self.append(att)
        return att

    def remove(self, index):  # noqa: A003 — mirrors the RNA API
        del self[index]


class FakeImages(dict):
    def get(self, name, default=None):  # noqa: A003
        return dict.get(self, name, default)


def _image(name, filepath=""):
    return SimpleNamespace(name=name, filepath=filepath, source='FILE')


def _board_item(image, selected=False):
    return SimpleNamespace(image=image, selected=selected, frame_id="")


def _scene(attachments, board_items=()):
    return SimpleNamespace(
        name="Scene",
        mixie_chat_pending_attachments=attachments,
        mixie_moodboard_images=list(board_items),
        mixie_moodboard_frames=[],
        mixie_moodboard_action_nodes=[],
    )


def _file_attachment(attachments, path):
    att = attachments.add()
    att.image_path = path
    att.image_source = 'FILE'
    att.display_name = Path(path).name
    return att


@pytest.fixture
def images(monkeypatch):
    store = FakeImages()
    monkeypatch.setattr(bpy.data, "images", store)
    return store


# ----------------------------------------------------------------- #
# Board → composer: a selected board copy of a dropped file adds no pill
# ----------------------------------------------------------------- #
def test_selected_board_copy_of_dropped_file_is_not_attached_twice(images):
    images["photo.png"] = _image("photo.png", PHOTO)
    attachments = FakeAttachments()
    _file_attachment(attachments, PHOTO)
    scene = _scene(attachments, [_board_item(images["photo.png"], selected=True)])

    chat_sync._reconcile_attachments(scene, ["photo.png"])

    assert len(attachments) == 1
    assert attachments[0].image_source == 'FILE'
    assert attachments[0].image_path == PHOTO


def test_selected_board_image_of_a_different_file_is_still_attached(images):
    images["other.png"] = _image("other.png", OTHER)
    attachments = FakeAttachments()
    _file_attachment(attachments, PHOTO)

    chat_sync._reconcile_attachments(_scene(attachments), ["other.png"])

    assert [(a.image_path, a.image_source, a.is_moodboard) for a in attachments] == [
        (PHOTO, 'FILE', False),
        ("other.png", 'BLEND_DATA', True),
    ]


def test_generated_board_image_without_a_file_is_attached(images):
    """No filepath means no FILE twin — the plain moodboard pill must appear."""
    images["Generated"] = _image("Generated", "")
    attachments = FakeAttachments()
    _file_attachment(attachments, PHOTO)

    chat_sync._reconcile_attachments(_scene(attachments), ["Generated"])

    assert [a.image_path for a in attachments] == [PHOTO, "Generated"]


def test_blend_data_name_match_still_dedupes(images):
    """The pre-existing rule: a manual blend-data pill of the same name."""
    images["tex.png"] = _image("tex.png", "")
    attachments = FakeAttachments()
    att = attachments.add()
    att.image_path, att.image_source = "tex.png", 'BLEND_DATA'

    chat_sync._reconcile_attachments(_scene(attachments), ["tex.png"])

    assert len(attachments) == 1


def test_board_image_is_attached_ignores_model_file_attachments(images):
    images["photo.png"] = _image("photo.png", PHOTO)
    attachments = FakeAttachments()
    att = attachments.add()
    att.image_path, att.image_source = PHOTO, 'MODEL_FILE'

    blend_names, file_keys = dedupe.attachment_identity_sets(attachments)

    assert blend_names == set() and file_keys == set()
    assert not dedupe.board_image_is_attached("photo.png", blend_names, file_keys)


# ----------------------------------------------------------------- #
# Removing the ONE pill releases the board selection it stood for
# ----------------------------------------------------------------- #
def test_removing_a_file_pill_deselects_its_board_copy(images):
    images["photo.png"] = _image("photo.png", PHOTO)
    board = [
        _board_item(images["photo.png"], selected=True),
        _board_item(_image("other.png", OTHER), selected=True),
    ]
    scene = _scene(FakeAttachments(), board)

    assert chat_sync.deselect_moodboard_image_for_attachment(scene, PHOTO, 'FILE')

    assert board[0].selected is False
    assert board[1].selected is True  # untouched


def test_removing_a_blend_data_pill_deselects_by_name(images):
    board = [_board_item(_image("tex.png", ""), selected=True)]
    scene = _scene(FakeAttachments(), board)

    assert chat_sync.deselect_moodboard_image_by_name(scene, "tex.png")

    assert board[0].selected is False


def test_deselect_reports_false_when_nothing_matched(images):
    board = [_board_item(_image("tex.png", ""), selected=True)]
    scene = _scene(FakeAttachments(), board)

    deselected = chat_sync.deselect_moodboard_image_for_attachment(scene, OTHER, 'FILE')

    assert deselected is False
    assert board[0].selected is True


# ----------------------------------------------------------------- #
# Composer → board: re-dropping a file whose board pill is up is a no-op
# ----------------------------------------------------------------- #
def test_find_attachment_for_file_sees_a_board_pill_of_that_file(images, monkeypatch):
    monkeypatch.setattr(bpy.path, "abspath", lambda p: p)
    images["photo.png"] = _image("photo.png", PHOTO)
    attachments = FakeAttachments()
    att = attachments.add()
    att.image_path, att.image_source, att.is_moodboard = "photo.png", 'BLEND_DATA', True

    assert attachment_board_sync.find_attachment_for_file(attachments, PHOTO) is att
    assert attachment_board_sync.find_attachment_for_file(attachments, OTHER) is None


def test_find_attachment_for_file_matches_file_pills_by_path(images):
    attachments = FakeAttachments()
    att = _file_attachment(attachments, PHOTO)

    assert attachment_board_sync.find_attachment_for_file(attachments, PHOTO) is att
    assert attachment_board_sync.find_attachment_for_file(attachments, "") is None


# ----------------------------------------------------------------- #
# Source-level pins (operator bodies are mocks under the bpy stub)
# ----------------------------------------------------------------- #
def test_remove_operator_deselects_for_file_pills_too():
    source = IMAGE_OPS.read_text(encoding="utf-8")
    assert "deselect_moodboard_image_for_attachment(" in source
    assert "if image_source in {'FILE', 'BLEND_DATA'}:" in source
    # The old moodboard-only gate must not come back.
    assert "if is_moodboard:" not in source


def test_file_attach_dedupes_through_the_shared_helper():
    source = IMAGE_OPS.read_text(encoding="utf-8")
    assert "find_attachment_for_file(attachments, filepath)" in source


def test_chat_sync_uses_the_shared_identity_rules():
    source = CHAT_SYNC.read_text(encoding="utf-8")
    deselect = CHAT_SYNC_DESELECT.read_text(encoding="utf-8")
    assert "board_image_is_attached(" in source
    assert "attachment_identity_sets(" in source
    assert "attachment_shows_board_item(" in deselect


@pytest.fixture
def staged_scene(images, monkeypatch):
    images.update({name: _image(name, '/tmp/'+name+'.png') for name in 'abcdefghijkl'})
    scene = _scene(FakeAttachments(), [_board_item(image) for image in images.values()])
    monkeypatch.setattr(bpy.context, 'scene', scene)
    monkeypatch.setattr(chat_sync, '_last_signatures', {})
    monkeypatch.setattr(chat_sync, '_ensure_graph_node_ids', lambda _: None)
    monkeypatch.setattr(chat_sync, '_redraw_chat_areas', lambda: None)
    monkeypatch.setattr(chat_sync, '_redraw_moodboard_areas', lambda: None)
    from mixar.modules.moodboard.core import attachment_motion
    monkeypatch.setattr(attachment_motion, 'animate_attachments', Mock())
    chat_sync._poll_tick()
    return scene


def _select(scene, *names):
    for item in scene.mixie_moodboard_images:
        item.selected = item.image.name in names
    chat_sync._poll_tick()


def _attached(scene):
    return [a.image_path for a in scene.mixie_chat_pending_attachments]


def test_selection_changes_and_empty_selection_drop_unselected_references(staged_scene):
    scene = staged_scene
    _select(scene, 'a')
    _select(scene, 'b')
    assert _attached(scene) == ['b']
    _select(scene)
    assert _attached(scene) == []
    _select(scene, 'a')
    assert _attached(scene) == ['a']


@pytest.mark.parametrize('kind', ['direct', 'frame', 'sibling', 'node', 'file'])
def test_explicit_remove_releases_the_board_selection(staged_scene, kind):
    scene = staged_scene
    item = scene.mixie_moodboard_images[0]
    if kind == 'frame':
        item.frame_id = 'frame-1'
        scene.mixie_moodboard_frames.append(
            SimpleNamespace(frame_id='frame-1', selected=True)
        )
    elif kind == 'sibling':
        item.frame_id = scene.mixie_moodboard_images[1].frame_id = 'frame-1'
        scene.mixie_moodboard_frames.append(
            SimpleNamespace(frame_id='frame-1', selected=False)
        )
        scene.mixie_moodboard_images[1].selected = True
    elif kind == 'node':
        scene.mixie_moodboard_action_nodes.append(
            SimpleNamespace(selected=True, preview_image=item.image)
        )
    else:
        item.selected = True
    if kind == 'file':
        _file_attachment(scene.mixie_chat_pending_attachments, item.image.filepath)
    chat_sync._poll_tick()
    attachment = scene.mixie_chat_pending_attachments[0]
    chat_sync.deselect_moodboard_image_for_attachment(
        scene, attachment.image_path, attachment.image_source
    )
    scene.mixie_chat_pending_attachments.remove(0)
    chat_sync._poll_tick()
    assert 'a' not in _attached(scene) and item.image.filepath not in _attached(scene)
    _select(scene, 'c')
    assert _attached(scene) == ['c']


def test_remove_does_not_drop_an_unrelated_unpolled_selection(staged_scene):
    scene = staged_scene
    _select(scene, 'a')
    scene.mixie_moodboard_images[1].selected = True
    chat_sync.deselect_moodboard_image_by_name(scene, 'a')
    scene.mixie_chat_pending_attachments.remove(0)
    chat_sync._poll_tick()
    assert _attached(scene) == ['b']


def test_cap_queues_overflow_until_a_slot_opens(staged_scene):
    scene = staged_scene
    _select(scene, *'abcdefghijkl')
    assert _attached(scene) == list('abcdefghij')
    scene.mixie_moodboard_images[0].selected = False
    chat_sync._poll_tick()
    assert _attached(scene) == list('bcdefghijk')
    _select(scene, 'l')
    assert _attached(scene) == ['l']


def test_explicit_clear_resyncs_from_the_current_selection(staged_scene):
    import ast
    scene = staged_scene
    _select(scene, 'a')
    scene.mixie_moodboard_images[1].selected = True
    tree = ast.parse(IMAGE_OPS.read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                 and n.name == 'MIXIE_CHAT_OT_clear_attachments')
    method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    namespace = dict(cleanup_loaded_file_images=Mock(), redraw_chat_areas=Mock())
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(IMAGE_OPS), 'exec'), namespace)
    assert namespace['execute'](SimpleNamespace(report=Mock()), SimpleNamespace(scene=scene)) == {'FINISHED'}
    chat_sync._poll_tick()
    assert _attached(scene) == ['a', 'b']
    _select(scene, 'b')
    assert _attached(scene) == ['b']


def test_send_deselects_attached_images_and_generated_nodes(staged_scene):
    scene = staged_scene
    scene.mixie_moodboard_action_nodes.append(SimpleNamespace(
        selected=True, preview_image=scene.mixie_moodboard_images[0].image))
    _select(scene, *'abcdefghijkl')
    assert len(_attached(scene)) == 10
    chat_sync.deselect_all_moodboard_origin_attachments(scene)
    scene.mixie_chat_pending_attachments.clear()
    chat_sync._poll_tick()
    assert _attached(scene) == ['k', 'l']
