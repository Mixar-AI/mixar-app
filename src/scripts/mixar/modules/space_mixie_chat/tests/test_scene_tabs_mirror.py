# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise mirror refresh with real logic and a counted RNA collection double."""
from types import SimpleNamespace

import pytest
from test_scene_tab_ops import rig  # noqa: F401
from _open_run_support import clean_state, live_bpy  # noqa: F401
from mixar.modules.space_mixie_chat.ui.properties import scene_tabs_props as props


class Tabs(list):
    writes = 0

    def clear(self):
        self.writes += 1
        super().clear()

    def add(self):
        tab = SimpleNamespace()
        self.append(tab)
        return tab


@pytest.fixture
def mirror(rig, monkeypatch):
    tabs = Tabs()
    wm = SimpleNamespace(mixar_scene_tabs=tabs, mixar_scene_tabs_attention=False)
    monkeypatch.setattr(props.bpy.context, 'window_manager', wm)
    monkeypatch.setattr(props, '_shown_scene', lambda: rig.windows[0].scene)
    monkeypatch.setattr(props, '_status_of', lambda scene: scene.mixie_chat_state)
    monkeypatch.setattr(props, '_workers', lambda sid: (0, 0))
    monkeypatch.setattr(props, '_tag_zen_viewports', lambda: None)
    monkeypatch.setattr(props, '_last_signature', ())
    monkeypatch.setattr(props, '_last_status', {})
    monkeypatch.setattr(props, '_finished_unseen', {})
    return tabs


def test_unchanged_refresh_does_not_rebuild_rna(mirror):
    assert props.refresh_scene_tabs() == 1
    row = mirror[0]
    for _ in range(10):
        assert props.refresh_scene_tabs() == 1
    assert mirror.writes == 1 and mirror[0] is row


def test_add_switch_rename_and_remove_refresh_immediately(rig, mirror):
    props.refresh_scene_tabs()
    b = rig.scenes.new('B')
    b.mixie_chat_state = 'IDLE'
    rig.windows[0].scene = b
    assert props.refresh_scene_tabs() == 2
    assert [t.scene_name for t in mirror if t.is_active] == ['B']
    b.name = 'Kitchen'
    props.refresh_scene_tabs()
    assert next(t for t in mirror if t.scene_uid == str(b.session_uid)).scene_name == 'Kitchen'
    rig.scenes.remove(rig.a)
    assert props.refresh_scene_tabs() == 1
    assert mirror[0].is_active and mirror[0].scene_name == 'Kitchen'


def test_empty_mirror_after_file_load_repopulates(mirror):
    props.refresh_scene_tabs()
    mirror.clear()
    assert props.refresh_scene_tabs() == 1
    assert mirror[0].scene_name == 'Scene'


def test_finished_attention_clears_when_scene_shown(rig, mirror):
    b = rig.scenes.new('B')
    b.mixie_session_id = 'sess-b'
    b.mixie_chat_state = 'WORKING'
    props.refresh_scene_tabs()
    b.mixie_chat_state = 'IDLE'
    props.refresh_scene_tabs()
    row = next(t for t in mirror if t.scene_uid == str(b.session_uid))
    assert row.status == 'DONE' and row.attention
    rig.windows[0].scene = b
    props.refresh_scene_tabs()
    row = next(t for t in mirror if t.scene_uid == str(b.session_uid))
    assert row.status == 'IDLE' and not row.attention
