# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Selected moodboard videos attach as context FILES (never pills) and follow
the board selection like image pills: a board-owned chip goes when its tile is
deselected, a picker chip for the same file never does
(``moodboard/core/chat_sync_videos.py``)."""

from types import SimpleNamespace

import pytest


def _modules():
    """Import lazily: a module-level import here would bind ``chat_sync`` (and
    its dedupe helper's ``bpy``) BEFORE a later-collected moodboard test swaps
    the global bpy mock, which strands ``test_chat_attachment_dedupe.py``."""
    from mixar.modules.moodboard.core import chat_sync, chat_sync_videos

    return chat_sync, chat_sync_videos


def _item(name, path, *, selected=True, movie=True, frame_id="", embedded_node_id=""):
    image = SimpleNamespace(name=name, source="MOVIE" if movie else "FILE", filepath=path)
    return SimpleNamespace(image=image, selected=selected, frame_id=frame_id,
                           embedded_node_id=embedded_node_id)


def _node(node_id, image, *, selected=True):
    """Fake Video Gen / Upscale action node holding its embedded result."""
    return SimpleNamespace(node_id=node_id, selected=selected, preview_image=image,
                           action_type="VIDEO_GEN")


class _Rows(list):
    """Fake ``Scene.mixie_context_files`` collection."""

    def add(self):
        item = SimpleNamespace(file_id="", name="", kind="", origin="")
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


@pytest.fixture
def registry(tmp_path):
    from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests

    registry = FolderRegistry(tmp_path / "registry" / "context_folders.json")
    set_registry_for_tests(registry)
    yield registry
    set_registry_for_tests(None)


def test_selected_videos_include_frame_members_and_skip_stills_and_idle_clips(tmp_path):
    chat_sync, chat_sync_videos = _modules()
    scene = SimpleNamespace(
        mixie_moodboard_images=[
            _item("clip", str(tmp_path / "clip.mp4")),
            _item("idle", str(tmp_path / "idle.mp4"), selected=False),
            _item("framed", str(tmp_path / "framed.mp4"), selected=False, frame_id="f1"),
            _item("still", str(tmp_path / "still.png"), movie=False),
        ],
        mixie_moodboard_frames=[SimpleNamespace(selected=True, frame_id="f1")],
        mixie_moodboard_action_nodes=[],
    )
    assert chat_sync_videos.selected_video_names(scene) == ("clip", "framed")
    # Stills stay out of the video hook and videos stay out of the pill list.
    assert chat_sync._collect_selected_image_names(scene) == ["still"]
    assert chat_sync._compute_selection_signature(scene)[2] == ("clip", "framed")


def test_video_chips_follow_the_board_selection_and_spare_picker_chips(tmp_path, registry):
    from mixar.modules.context_folder.core.files import attach_file

    _, chat_sync_videos = _modules()
    for name in ("clip.mp4", "framed.mp4", "mine.mp4"):
        (tmp_path / name).write_bytes(b"x")
    items = [_item("clip", str(tmp_path / "clip.mp4")),
             _item("framed", str(tmp_path / "framed.mp4")),
             _item("gone", str(tmp_path / "gone.mp4")),
             _item("mine", str(tmp_path / "mine.mp4"), selected=False)]
    scene = SimpleNamespace(mixie_context_files=_Rows(), mixie_context_files_id="",
                            mixie_moodboard_images=items, mixie_moodboard_frames=[],
                            mixie_moodboard_action_nodes=[])
    # A chip the user attached through the picker for a board video.
    assert attach_file(scene, str(tmp_path / "mine.mp4"))["success"]

    # Select → chip, idempotent; a missing movie is skipped.
    assert chat_sync_videos.sync_selected_videos(scene) == (2, 0)
    assert [(row.name, row.origin) for row in scene.mixie_context_files] == [
        ("mine.mp4", "picker"), ("clip.mp4", "moodboard"), ("framed.mp4", "moodboard")]
    assert chat_sync_videos.sync_selected_videos(scene) == (0, 0)

    # Deselect → the board-owned chip is gone; the picker chip survives even
    # when ITS tile is selected then deselected (a re-attach keeps the origin).
    items[0].selected = False
    items[3].selected = True
    assert chat_sync_videos.sync_selected_videos(scene) == (0, 1)
    items[3].selected = False
    assert chat_sync_videos.sync_selected_videos(scene) == (0, 0)
    assert [(row.name, row.origin) for row in scene.mixie_context_files] == [
        ("mine.mp4", "picker"), ("framed.mp4", "moodboard")]
    # The registry no longer serves the detached clip under the scene's set.
    members = {name for name, _ in registry.resolve(scene.mixie_context_files_id).members}
    assert members == {"mine.mp4", "framed.mp4"}

    assert chat_sync_videos.sync_selected_videos(SimpleNamespace()) == (0, 0)  # no prop: no-op


def test_a_refused_attach_is_logged_not_raised(tmp_path, registry, monkeypatch):
    from unittest.mock import Mock

    from mixar.modules.context_folder import constants

    _, chat_sync_videos = _modules()
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setattr(constants, "MAX_CONTEXT_FILES", 1)
    monkeypatch.setattr("mixar.modules.context_folder.core.files.MAX_CONTEXT_FILES", 1)
    scene = SimpleNamespace(mixie_context_files=_Rows(), mixie_context_files_id="",
                            mixie_moodboard_images=[_item("a", str(tmp_path / "a.mp4")),
                                                    _item("b", str(tmp_path / "b.mp4"))],
                            mixie_moodboard_frames=[], mixie_moodboard_action_nodes=[])
    log = Mock()
    monkeypatch.setattr(chat_sync_videos._logger, "info", log)
    assert chat_sync_videos.sync_selected_videos(scene) == (1, 0)
    assert len(scene.mixie_context_files) == 1
    log.assert_called_once()
    assert "not attached as context" in log.call_args.args[0]


def test_a_selected_video_node_result_is_a_selected_video_but_never_a_pill(tmp_path):
    """A Video Gen / Upscale result is an EMBEDDED item whose own ``selected``
    stays False (node_graph.connect_video_result); the click selects its
    owning node. The clip must still count as selected — once — without
    becoming a still pill."""
    chat_sync, chat_sync_videos = _modules()
    generated = _item("gen", str(tmp_path / "gen.mp4"), selected=False,
                      embedded_node_id="n1", frame_id="f1")
    other = _item("other", str(tmp_path / "other.mp4"), selected=False,
                  embedded_node_id="n2")
    scene = SimpleNamespace(
        mixie_moodboard_images=[_item("clip", str(tmp_path / "clip.mp4")), generated, other],
        # The generated clip also sits in a selected frame: still one entry.
        mixie_moodboard_frames=[SimpleNamespace(selected=True, frame_id="f1")],
        mixie_moodboard_action_nodes=[_node("n1", generated.image),
                                      _node("n2", other.image, selected=False)],
    )
    assert [item.image.name for item in chat_sync_videos.selected_video_items(scene)] == [
        "clip", "gen"]
    assert chat_sync._compute_selection_signature(scene)[2] == ("clip", "gen")
    # The node's MOVIE preview never becomes a pill.
    assert chat_sync._collect_selected_image_names(scene) == []

    # Node ownership alone admits it (no frame, item.selected still False)...
    scene.mixie_moodboard_frames[0].selected = False
    assert chat_sync_videos.selected_video_names(scene) == ("clip", "gen")
    # ...and deselecting the node drops it.
    scene.mixie_moodboard_action_nodes[0].selected = False
    assert chat_sync_videos.selected_video_names(scene) == ("clip",)


def test_a_video_node_chip_follows_the_node_selection(tmp_path, registry):
    _, chat_sync_videos = _modules()
    (tmp_path / "gen.mp4").write_bytes(b"x")
    generated = _item("gen", str(tmp_path / "gen.mp4"), selected=False, embedded_node_id="n1")
    node = _node("n1", generated.image)
    scene = SimpleNamespace(mixie_context_files=_Rows(), mixie_context_files_id="",
                            mixie_moodboard_images=[generated], mixie_moodboard_frames=[],
                            mixie_moodboard_action_nodes=[node])

    assert chat_sync_videos.sync_selected_videos(scene) == (1, 0)
    assert [(row.name, row.origin) for row in scene.mixie_context_files] == [
        ("gen.mp4", "moodboard")]
    assert chat_sync_videos.sync_selected_videos(scene) == (0, 0)

    node.selected = False
    assert chat_sync_videos.sync_selected_videos(scene) == (0, 1)
    assert list(scene.mixie_context_files) == []


def test_only_new_committed_videos_animate(tmp_path, registry, monkeypatch):
    from unittest.mock import Mock
    from mixar.modules.moodboard.core import attachment_motion
    _, sync = _modules()
    animate = Mock()
    monkeypatch.setattr(attachment_motion, 'animate_attachments', animate)
    for name in ('a.mp4', 'b.mp4'):
        (tmp_path / name).write_bytes(b'x')
    items = [_item('a', str(tmp_path / 'a.mp4')),
             _item('b', str(tmp_path / 'b.mp4'), selected=False),
             _item('missing', str(tmp_path / 'missing.mp4'))]
    scene = SimpleNamespace(mixie_context_files=_Rows(), mixie_context_files_id='',
                            mixie_moodboard_images=items, mixie_moodboard_frames=[],
                            mixie_moodboard_action_nodes=[])
    assert sync.sync_selected_videos(scene) == (1, 0)  # startup is quiet
    animate.assert_not_called()
    items[1].selected = True
    assert sync.sync_selected_videos(scene, animate=True) == (1, 0)
    animate.assert_called_once_with(scene, ['b'], context_file_ids={
        'b': scene.mixie_context_files[1].file_id})
    animate.reset_mock()
    assert sync.sync_selected_videos(scene, animate=True) == (0, 0)
    items[1].selected = False
    assert sync.sync_selected_videos(scene, animate=True) == (0, 1)
    animate.assert_not_called()


def test_refused_video_attach_does_not_animate(tmp_path, registry, monkeypatch):
    from unittest.mock import Mock
    from mixar.modules.moodboard.core import attachment_motion
    _, sync = _modules()
    animate = Mock()
    monkeypatch.setattr(attachment_motion, 'animate_attachments', animate)
    monkeypatch.setattr('mixar.modules.context_folder.core.files.MAX_CONTEXT_FILES', 0)
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'x')
    scene = SimpleNamespace(mixie_context_files=_Rows(), mixie_context_files_id='',
                            mixie_moodboard_images=[_item('clip', str(path))],
                            mixie_moodboard_frames=[], mixie_moodboard_action_nodes=[])
    assert sync.sync_selected_videos(scene, animate=True) == (0, 0)
    animate.assert_not_called()


def test_poll_animates_video_selection_changes_only(monkeypatch):
    from unittest.mock import Mock
    chat_sync, _ = _modules()
    scene = SimpleNamespace(name='video motion')
    monkeypatch.setattr(chat_sync, 'bpy', SimpleNamespace(context=SimpleNamespace(scene=scene)))
    monkeypatch.setattr(chat_sync, '_last_signatures', {})
    monkeypatch.setattr(chat_sync, '_ensure_graph_node_ids', lambda _: None)
    monkeypatch.setattr(chat_sync, '_migrate_legacy_frames', lambda _: None)
    monkeypatch.setattr(chat_sync, '_reconcile_attachments', Mock())
    signature = [0, (), ()]
    monkeypatch.setattr(chat_sync, '_compute_selection_signature', lambda _: tuple(signature))
    sync = Mock(return_value=(0, 0))
    monkeypatch.setattr(chat_sync, 'sync_selected_videos', sync)
    chat_sync._poll_tick()
    sync.assert_called_once_with(scene, animate=False)
    sync.reset_mock()
    signature[2] = ('movie',)
    chat_sync._poll_tick()
    sync.assert_called_once_with(scene, animate=True)
    sync.reset_mock()
    chat_sync._poll_tick()
    sync.assert_not_called()
    signature[0] = 1  # Attachment drift does not replay selection feedback.
    chat_sync._poll_tick()
    sync.assert_called_once_with(scene, animate=False)
