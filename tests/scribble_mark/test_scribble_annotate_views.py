# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Done previews each frozen view; clean companions never enter the composer."""

from types import SimpleNamespace

import pytest

from mixar.modules.scribble_mark.core import preview, view_bake
from mixar.modules.space_mixie_chat.core import ui_utils

VIEW_CURRENT = 'mixar_mark_view_0007'
VIEW_OLDER = 'mixar_mark_view_0003'
FRAME_CURRENT = 'mixar_mark_frame_0007'
FRAME_OLDER = 'mixar_mark_frame_0003'


class Attachments(list):
    def add(self):
        item = SimpleNamespace(image_source='', image_path='', display_name='', scribble_view='')
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def mark(serial, view):
    return {'id': serial, 'view': view, 'strokes': [[[.1, .1], [.9, .9]]]}


@pytest.fixture
def rig(monkeypatch):
    scene = SimpleNamespace(mixie_chat_pending_attachments=Attachments(), mixie_chat_messages=[])
    images = {name: SimpleNamespace(name=name) for name in (FRAME_CURRENT, FRAME_OLDER)}
    drafts, rendered = [], []

    def render(image, ink, name):
        rendered.append((image.name, list(ink), name))
        images[name] = SimpleNamespace(name=name)
        return name

    monkeypatch.setattr(preview.freeze, 'get_image', images.get)
    monkeypatch.setattr(preview.freeze, 'release', lambda name: images.pop(name, None))
    monkeypatch.setattr(preview.annotate, 'render_annotated', render)
    monkeypatch.setattr(preview.mark_store, 'draft_marks', lambda scene: drafts)
    monkeypatch.setattr(ui_utils, 'redraw_chat_areas', lambda: None)
    return SimpleNamespace(scene=scene, images=images, drafts=drafts, rendered=rendered,
                           pending=scene.mixie_chat_pending_attachments)


def test_frame_view_identity_is_reversible():
    assert view_bake.view_name_for_frame(FRAME_CURRENT) == VIEW_CURRENT
    assert preview.frame_for_view(VIEW_CURRENT) == FRAME_CURRENT
    for value in ('', 'not_a_view_7', 'mixar_mark_view_no_serial', None):
        assert preview.frame_for_view(value) == ''


def test_each_view_previews_only_its_own_raw_ink(rig):
    older, current = mark(3, VIEW_OLDER), mark(7, VIEW_CURRENT)
    rig.drafts.extend([older, current])
    assert preview.sync(rig.scene) == []
    assert [(frame, ink) for frame, ink, _ in rig.rendered] == [
        (FRAME_OLDER, [older]), (FRAME_CURRENT, [current])]
    assert len(rig.pending) == 2
    assert [att.scribble_view for att in rig.pending] == [VIEW_OLDER, VIEW_CURRENT]
    assert all('annotated' in att.image_path for att in rig.pending)


def test_clean_frames_join_only_the_outgoing_list(rig):
    rig.drafts.append(mark(7, VIEW_CURRENT))
    preview.sync(rig.scene)
    visible = list(rig.pending)
    outgoing = preview.outgoing_attachments(rig.scene)
    assert len(outgoing) == 2 and outgoing[0] is visible[0]
    assert outgoing[1].image_path == FRAME_CURRENT
    assert list(rig.pending) == visible


def test_retry_reuses_the_preview_without_repainting_or_duplicating(rig):
    rig.drafts.append(mark(7, VIEW_CURRENT))
    preview.sync(rig.scene)
    preview.sync(rig.scene)
    assert len(rig.rendered) == len(rig.pending) == 1
    assert len(preview.outgoing_attachments(rig.scene)) == 2


def test_undo_refreshes_ink_and_releases_the_obsolete_preview(rig):
    rig.drafts.extend([mark(7, VIEW_CURRENT), mark(8, VIEW_CURRENT)])
    preview.sync(rig.scene)
    old = rig.pending[0].image_path
    rig.drafts.pop()
    preview.sync(rig.scene)
    assert len(rig.pending) == 1
    assert rig.rendered[-1][1] == rig.drafts
    assert rig.pending[0].image_path != old and old not in rig.images


def test_discarded_drafts_do_not_remove_sent_images_or_manual_references(rig):
    rig.drafts.append(mark(7, VIEW_CURRENT))
    preview.sync(rig.scene)
    sent = SimpleNamespace(attachments=list(rig.pending))
    rig.scene.mixie_chat_messages.append(sent)
    manual = rig.pending.add()
    manual.image_path, manual.image_source = '/tmp/reference.png', 'FILE'
    rig.drafts.clear()
    preview.sync(rig.scene)
    assert list(rig.pending) == [manual]
    assert sent.attachments[0].image_path in rig.images
    assert preview.outgoing_attachments(rig.scene) == [manual]


def test_all_visible_references_take_priority_over_clean_companions(rig):
    for i in range(9):
        att = rig.pending.add()
        att.image_path, att.image_source = f'/tmp/{i}.png', 'FILE'
    rig.drafts.append(mark(7, VIEW_CURRENT))
    assert preview.sync(rig.scene) == []
    assert len(rig.pending) == len(preview.outgoing_attachments(rig.scene)) == 10
    assert rig.pending[-1].scribble_view == VIEW_CURRENT


def test_full_composer_explains_how_to_recover(rig):
    for _ in range(10):
        rig.pending.add()
    rig.drafts.append(mark(7, VIEW_CURRENT))
    assert any('Remove a reference' in note for note in preview.sync(rig.scene))
    assert len(rig.pending) == 10 and not rig.rendered
    rig.pending.remove(0)
    assert preview.sync(rig.scene) == []
    assert rig.pending[-1].scribble_view == VIEW_CURRENT


def test_failed_annotation_never_presents_a_clean_frame_as_the_sketch(rig, monkeypatch):
    rig.drafts.append(mark(7, VIEW_CURRENT))
    monkeypatch.setattr(preview.annotate, 'render_annotated', lambda *args: None)
    assert any('Draw again' in note for note in preview.sync(rig.scene))
    assert not rig.pending and not preview.outgoing_attachments(rig.scene)
    assert len(rig.drafts) == 1


def test_removing_a_preview_discards_only_its_view_and_resets_intent_when_empty(rig, monkeypatch):
    from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
    wm = SimpleNamespace(mixar_mark_intent='POINT')
    rig.drafts.extend([mark(3, VIEW_OLDER), mark(7, VIEW_CURRENT)])
    preview.sync(rig.scene)

    def clear(scene, *, drafts_only, view, keep_view):
        assert drafts_only and keep_view == ''
        rig.drafts[:] = [m for m in rig.drafts if m['view'] != view]

    monkeypatch.setattr(mark_draw_ops, 'live_view_name', lambda: '')
    monkeypatch.setattr(preview.mark_store, 'clear', clear)
    monkeypatch.setattr(preview.mark_store, 'view_referenced',
                        lambda scene, view: any(m['view'] == view for m in rig.drafts))
    monkeypatch.setattr(preview.mark_store, 'has_drafts', lambda scene: bool(rig.drafts))
    monkeypatch.setattr(preview.mark_store, 'refresh_reading', lambda *args: None)
    monkeypatch.setattr(preview.mark_store.overlay, 'tag_redraw', lambda: None)
    preview.discard_view(rig.scene, wm, VIEW_CURRENT)
    assert [a.scribble_view for a in rig.pending] == [VIEW_OLDER]
    assert FRAME_CURRENT not in rig.images and FRAME_OLDER in rig.images
    assert wm.mixar_mark_intent == 'POINT'
    preview.discard_view(rig.scene, wm, VIEW_OLDER)
    assert not rig.pending and not rig.drafts and wm.mixar_mark_intent == 'AUTO'
