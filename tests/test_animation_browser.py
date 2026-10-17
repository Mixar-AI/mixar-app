# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Clip ownership, slot isolation and discovery; preview contracts live in
``test_animation_preview.py``."""
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


def target(bindings=(), valid=('location',)):
    def resolve(path):
        if path not in valid:
            raise ValueError(path)
        return [0, 0, 0]
    return NS(id_type='OBJECT', path_resolve=resolve,
              animation_data=NS(action=bindings[0].action if bindings else None,
                                action_slot=bindings[0].action_slot if bindings else None,
                                nla_tracks=[NS(strips=list(bindings[1:]))]))


def binding(action, slot):
    return NS(type='CLIP', action=action, action_slot=slot)


def test_selected_scope_includes_active_and_stashed_actions_without_duplicates():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Character')
    idle = action('Idle', [(slot, [curve()])])
    walk = action('Walk', [(slot, [curve()])])
    owned = target([binding(idle, slot), binding(walk, slot), binding(walk, slot)])
    rows = list(catalog.entries(owned, [idle, walk]))
    assert [r['action_name'] for r in rows] == ['Idle', 'Walk']
    assert all(r['used'] and not r['reason'] for r in rows)


def test_all_file_includes_unassigned_actions_but_checks_bone_paths():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Rig')
    walk = action('Walk', [(slot, [curve()])])
    wings = action('Flap', [(slot, [curve('pose.bones["Wing"].rotation_euler')])])
    rows = list(catalog.entries(target(), [walk, wings], all_in_file=True))
    assert not rows[0]['reason'] and not rows[0]['used']
    assert rows[1]['reason'] and not rows[1]['used']


def test_multi_slot_clip_range_and_compatibility_never_read_sibling_curves():
    body = NS(handle=11, target_id_type='OBJECT', name_display='Body')
    light = NS(handle=22, target_id_type='LIGHT', name_display='Light')
    shared = action('Take', [(body, [curve(end=49)]), (light, [curve('energy', end=999)])])
    rows = list(catalog.entries(target([binding(shared, body)]), [shared]))
    assert len(rows) == 1 and rows[0]['end'] == 49 and not rows[0]['reason']
    all_rows = list(catalog.entries(target(), [shared], all_in_file=True))
    assert len(all_rows) == 2 and all_rows[1]['reason']


def test_no_selection_cannot_preview_and_empty_slot_is_disabled():
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Rig')
    empty = action('Empty', [(slot, [])])
    assert next(catalog.entries(None, [empty], True))['reason']
    assert next(catalog.entries(target(), [empty], True))['reason']


def test_nested_meta_strips_are_discovered():
    slot = NS(handle=1, target_id_type='OBJECT', name_display='Rig')
    walk = action('Walk', [(slot, [curve()])])
    owner = target()
    owner.animation_data.nla_tracks = [NS(strips=[NS(type='META', strips=[binding(walk, slot)])])]
    assert next(catalog.entries(owner, []))['action_name'] == 'Walk'


def test_manual_range_wins_over_other_slots_and_curve_extents():
    clip = NS(use_frame_range=True, frame_start=5, frame_end=15)
    assert catalog.clip_range(clip, [curve(end=100)]) == (5, 15)


def test_render_sweep_removes_only_private_render_scenes(monkeypatch):
    # Animation preview no longer creates scenes; only render scenes are internal.
    user, render = {}, {INTERNAL_RENDER_SCENE_PROP: True}
    assert not is_internal_scene(user) and is_internal_scene(render)
    assert not is_internal_scene({'mixar_internal_animation_scene': True})
    scenes = MagicMock()
    scenes.__iter__.return_value = iter([user, render])
    monkeypatch.setattr(render_scene, 'bpy', NS(data=NS(scenes=scenes)))
    render_scene.sweep()
    scenes.remove.assert_called_once_with(render, do_unlink=True)


def test_selected_mesh_resolves_its_rig_but_deselected_active_id_does_not():
    rig = NS(name='Rig')
    mesh = NS(type='MESH', select_get=lambda **kw: True, find_armature=lambda: rig)
    context = NS(view_layer=NS(objects=NS(active=mesh)), scene=NS(objects={'Rig': rig}))
    assert catalog.selected_target(context) is rig
    mesh.select_get = lambda **kw: False
    assert catalog.selected_target(context) is None
