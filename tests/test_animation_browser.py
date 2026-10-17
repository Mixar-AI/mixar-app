# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Clip rows, slot isolation and discovery; the NLA actions behind the row
buttons live in ``test_animation_nla.py``."""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from mixar.modules.workflow.core import animation_catalog as catalog
from mixar.modules.common.render_coordinator.constants import (
    INTERNAL_RENDER_SCENE_PROP, is_internal_scene,
)
from mixar.modules.space_mixie_chat.core import render_scene


def curve(path='location', start=1, end=25, index=0):
    return NS(data_path=path, array_index=index, keyframe_points=[1, 2],
              sampled_points=[], range=lambda: (start, end))


def action(name, slots):
    return NS(name=name, slots=[s for s, _ in slots], use_frame_range=False,
              frame_range=(1, 1000), layers=[NS(strips=[NS(channelbags=[
                  NS(slot_handle=s.handle, fcurves=curves) for s, curves in slots])])])


def strip(action, slot, name=None, start=1, end=25):
    return NS(type='CLIP', action=action, action_slot=slot, name=name or action.name,
              frame_start=start, frame_end=end)


def track(name, *strips, solo=False, mute=False):
    return NS(name=name, strips=list(strips), is_solo=solo, mute=mute)


def target(active=None, tracks=(), valid=('location',)):
    def resolve(path):
        if path not in valid:
            raise ValueError(path)
        return [0, 0, 0]
    return NS(id_type='OBJECT', path_resolve=resolve,
              animation_data=NS(action=active[0] if active else None,
                                action_slot=active[1] if active else None,
                                nla_tracks=list(tracks)))


def test_selected_scope_lists_active_action_then_every_strip_with_its_track():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Character')
    idle = action('Idle', [(slot, [curve()])])
    walk = action('Walk', [(slot, [curve()])])
    owned = target((idle, slot), [track('Walk stored', strip(walk, slot, start=10, end=34),
                                        strip(walk, slot, 'Walk.001', 40, 64), mute=True)])
    rows = list(catalog.entries(owned, [idle, walk]))
    assert [(r['kind'], r['action_name'], r['track_name'], r['strip_name']) for r in rows] == [
        ('ACTION', 'Idle', '', ''), ('STRIP', 'Walk', 'Walk stored', 'Walk'),
        ('STRIP', 'Walk', 'Walk stored', 'Walk.001')]
    assert all(r['used'] and not r['reason'] for r in rows)
    # A strip row's range is the strip on the timeline: what Play previews.
    assert (rows[2]['start'], rows[2]['end']) == (40.0, 64.0)


def test_all_in_file_marks_clips_on_the_target_and_checks_bone_paths():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Rig')
    idle = action('Idle', [(slot, [curve()])])
    walk = action('Walk', [(slot, [curve()])])
    jump = action('Jump', [(slot, [curve()])])
    wings = action('Flap', [(slot, [curve('pose.bones["Wing"].rotation_euler')])])
    owner = target((idle, slot), [track('Walk', strip(walk, slot))])
    rows = {r['action_name']: r for r in catalog.entries(
        owner, [idle, walk, jump, wings], all_in_file=True)}
    assert rows['Idle']['kind'] == 'ACTION' and rows['Walk']['kind'] == 'STRIP'
    assert rows['Walk']['track_name'] == 'Walk'
    assert rows['Jump']['kind'] == 'FILE' and not rows['Jump']['used']
    assert not rows['Jump']['reason'] and rows['Flap']['reason']


def test_multi_slot_clip_range_and_compatibility_never_read_sibling_curves():
    body = NS(handle=11, target_id_type='OBJECT', name_display='Body')
    light = NS(handle=22, target_id_type='LIGHT', name_display='Light')
    shared = action('Take', [(body, [curve(end=49)]), (light, [curve('energy', end=999)])])
    rows = list(catalog.entries(target((shared, body)), [shared]))
    assert len(rows) == 1 and rows[0]['end'] == 49 and not rows[0]['reason']
    assert rows[0]['slot_name'] == 'Body'
    all_rows = list(catalog.entries(target(), [shared], all_in_file=True))
    assert len(all_rows) == 2 and all_rows[1]['reason']


def test_no_selection_cannot_play_and_empty_slot_is_disabled():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Rig')
    empty = action('Empty', [(slot, [])])
    assert next(catalog.entries(None, [empty], True))['reason']
    assert next(catalog.entries(target(), [empty], True))['reason']


def test_nested_meta_strips_are_discovered_and_flagged():
    slot = NS(handle=1, target_id_type='OBJECT', name_display='Rig')
    walk = action('Walk', [(slot, [curve()])])
    owner = target(tracks=[track('Combo', NS(type='META', strips=[strip(walk, slot)]))])
    row = next(catalog.entries(owner, []))
    assert (row['action_name'], row['track_name'], row['nested']) == ('Walk', 'Combo', True)
    assert catalog.find_strip(owner, 'Combo', 'Walk')[2] is True


def test_soloed_track_reads_the_nla_flag():
    owner = target(tracks=[track('A'), track('B', solo=True)])
    assert catalog.soloed_track(owner).name == 'B'
    assert catalog.soloed_track(target()) is None


def test_manual_range_wins_over_other_slots_and_curve_extents():
    clip = NS(use_frame_range=True, frame_start=5, frame_end=15)
    assert catalog.clip_range(clip, [curve(end=100)]) == (5, 15)


def test_render_sweep_removes_only_private_render_scenes(monkeypatch):
    # The animation browser never creates scenes; only render scenes are internal.
    user, render = {}, {INTERNAL_RENDER_SCENE_PROP: True}
    assert not is_internal_scene(user) and is_internal_scene(render)
    assert not is_internal_scene({'mixar_internal_animation_scene': True})
    scenes = MagicMock()
    scenes.__iter__.return_value = iter([user, render])
    monkeypatch.setattr(render_scene, 'bpy', NS(data=NS(scenes=scenes)))
    render_scene.sweep()
    scenes.remove.assert_called_once_with(render, do_unlink=True)


def test_selected_mesh_resolves_its_rig_but_deselected_active_id_does_not():
    rig = NS(name='Rig', type='ARMATURE')
    mesh = NS(type='MESH', select_get=lambda **kw: True, find_armature=lambda: rig)
    context = NS(view_layer=NS(objects=NS(active=mesh)), scene=NS(objects={'Rig': rig}))
    assert catalog.selected_target(context) is rig
    assert catalog.hidable_rig(context) is rig
    mesh.select_get = lambda **kw: False
    assert catalog.selected_target(context) is None


def test_a_selected_rig_is_never_offered_hide_rig():
    rig = NS(name='Rig', type='ARMATURE', select_get=lambda **kw: True)
    context = NS(view_layer=NS(objects=NS(active=rig)), scene=NS(objects={'Rig': rig}))
    assert catalog.selected_target(context) is rig
    assert catalog.hidable_rig(context) is None


def _watch_env(monkeypatch, popovers_open):
    from mixar.modules.workflow.core import animation_browser as browser
    state = NS(search='', scope='ALL', clips=MagicMock(), active_index=0,
               target_name='', loading=False)
    fake_bpy = MagicMock()
    fake_bpy.context.window_manager.mixar_animations = state
    fake_bpy.data.actions = []
    monkeypatch.setattr(browser, 'bpy', fake_bpy)
    window = MagicMock()
    window.workspace.name = browser.BASIC_WORKSPACE_NAME
    window.mixar_refresh_popover.return_value = popovers_open
    area = MagicMock(type='VIEW_3D')
    monkeypatch.setattr(browser, 'host', lambda: (window, area))
    monkeypatch.setattr(browser, '_host', (1, 2))
    monkeypatch.setattr(browser, '_signature', None)
    monkeypatch.setattr(browser, '_scan', None)
    scanned = []
    monkeypatch.setattr(browser.catalog, 'selected_target', lambda _context: None)
    monkeypatch.setattr(browser.catalog, 'entries',
                        lambda *args: scanned.append(args) or iter(()))
    return browser, area, scanned


def test_closed_browser_stops_scanning_and_unbinds(monkeypatch):
    # A selection change after the popover closed must not rescan or redraw.
    browser, area, scanned = _watch_env(monkeypatch, popovers_open=0)
    assert browser._watch() is None
    assert browser._host is None and not scanned
    area.tag_redraw.assert_not_called()


def test_open_browser_scans_and_tags_only_the_popover(monkeypatch):
    browser, area, scanned = _watch_env(monkeypatch, popovers_open=1)
    assert browser._watch() is None
    assert scanned and browser._host == (1, 2)
    area.tag_redraw.assert_not_called()
