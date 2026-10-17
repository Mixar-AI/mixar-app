# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""NLA-style animation preview: snapshot -> assign -> restore on the real target."""
from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest

from mixar.modules.workflow.core import animation_catalog as catalog
from mixar.modules.workflow.core import animation_preview as preview
from mixar.modules.workflow.core import animation_snapshot as snapshots

ARM = 'pose.bones["Arm.L"].rotation_euler'
ROOT = 'pose.bones["Root"].location'


class AnimData(NS):
    pass


class Target:
    """Minimal Object: pose channels, a custom property and animation data."""

    def __init__(self, anim=None, kind='ARMATURE'):
        self.name, self.type, self.id_type = 'Rig', kind, 'OBJECT'
        self.animation_data = anim
        self.pose = NS(bones={'Arm.L': NS(rotation_euler=[0.0, 0.0, 0.0]),
                              'Root': NS(location=[0.0, 0.0, 0.0])})
        self.props = {'weight': 0.5}
        self.hidden, self.selected = False, True

    def __getitem__(self, key):
        return self.props[key]

    def __setitem__(self, key, value):
        self.props[key] = value

    def path_resolve(self, path):
        return eval(('self' if path.startswith('[') else 'self.') + path, {'self': self})

    def animation_data_create(self):
        if self.animation_data is None:
            self.animation_data = AnimData(
                action=None, action_slot=None, use_nla=True, action_blend_type='REPLACE',
                action_influence=1.0, action_extrapolation='HOLD_FORWARD',
                last_slot_identifier='', use_tweak_mode=False)
        return self.animation_data

    def animation_data_clear(self):
        self.animation_data = None

    def hide_get(self, view_layer=None):
        return self.hidden

    def hide_set(self, value, view_layer=None):
        self.hidden = value
        if value:
            self.selected = False

    def select_get(self, view_layer=None):
        return self.selected

    def select_set(self, value, view_layer=None):
        self.selected = value


class Scene(NS):
    def frame_set(self, frame, subframe=0.0):
        self.frame_current, self.frame_subframe = frame, subframe
        self.calls.append((frame, subframe))


def curve(path, index, end=49):
    return NS(data_path=path, array_index=index, keyframe_points=[1, 2],
              sampled_points=[], range=lambda: (1, end))


def clip(name, curves, slot):
    return NS(name=name, slots=[slot], use_frame_range=False, frame_range=(1, 49),
              layers=[NS(strips=[NS(channelbags=[NS(slot_handle=slot.handle, fcurves=curves)])])])


def original_anim():
    return AnimData(action='Idle', action_slot='IdleSlot', use_nla=True,
                    action_blend_type='ADD', action_influence=.4,
                    action_extrapolation='HOLD_FORWARD', last_slot_identifier='OBIdle',
                    use_tweak_mode=False)


def scene():
    layer = NS(name='ViewLayer')
    return Scene(frame_current=7, frame_subframe=.25, calls=[],
                 render=NS(fps=24, fps_base=1), view_layers={'ViewLayer': layer})


def test_split_path_handles_quoted_dots_brackets_and_custom_properties():
    assert snapshots.split_path(ARM) == ('pose.bones["Arm.L"]', 'rotation_euler', False)
    assert snapshots.split_path('pose.bones["a[1]"]["x.y"]') == ('pose.bones["a[1]"]', 'x.y', True)
    assert snapshots.split_path('["weight"]') == ('', 'weight', True)
    assert snapshots.split_path('location') == ('', 'location', False)


def test_round_trip_restores_settings_written_channels_and_frame():
    target, s = Target(original_anim()), scene()
    curves = [curve(ARM, 1), curve(ROOT, 0), curve('["weight"]', 0),
              curve('pose.bones["Missing"].location', 0)]
    snap = snapshots.capture(target, s, curves)
    assert set(snap.values) == {(ARM, 1), (ROOT, 0), ('["weight"]', 0)}
    snapshots.assign(target, 'Wave', 'WaveSlot')
    anim = target.animation_data
    assert (anim.action, anim.action_slot, anim.use_nla, anim.action_blend_type,
            anim.action_influence, anim.action_extrapolation) == (
        'Wave', 'WaveSlot', False, 'REPLACE', 1.0, 'HOLD')
    # What evaluating the clip would write.
    target.pose.bones['Arm.L'].rotation_euler[1] = 1.3
    target.pose.bones['Root'].location[0] = 2.0
    target['weight'] = 1.0
    anim.last_slot_identifier = 'OBWave'
    s.frame_set(25)
    assert snapshots.restore(snap, target, s)
    assert anim == original_anim()
    assert target.pose.bones['Arm.L'].rotation_euler == [0, 0, 0]
    assert target.pose.bones['Root'].location == [0, 0, 0]
    assert target['weight'] == .5
    assert s.calls[-1] == (7, .25)
    assert snapshots.restore(snap, target, s)  # idempotent


def test_restore_removes_animation_data_that_did_not_exist():
    target, s = Target(), scene()
    snap = snapshots.capture(target, s, [curve(ROOT, 2)])
    snapshots.assign(target, 'Walk', None)
    target.pose.bones['Root'].location[2] = 3.0
    snapshots.restore(snap, target, s)
    assert target.animation_data is None
    assert target.pose.bones['Root'].location == [0, 0, 0]


class Window(NS):
    def as_pointer(self):
        return self.ptr

    def mixar_refresh_popover(self, _name):
        return 0


@pytest.fixture
def env(monkeypatch):
    s = scene()
    area = NS(type='VIEW_3D', as_pointer=lambda: 20, tag_redraw=lambda: None)
    playing = []
    window = Window(ptr=10, scene=s, view_layer=s.view_layers['ViewLayer'], workspace='Zen',
                    screen=NS(is_animation_playing=False, areas=[area]))
    state = NS(clips=[], error=False, preview_name='', active_index=0, playing=False,
               hide_rig=False, loop=True)
    wm = NS(windows=[window], mixar_animations=state)
    slot = NS(handle=11, target_id_type='OBJECT', name_display='Rig')
    actions = {'Wave': clip('Wave', [curve(ARM, 1)], slot),
               'Walk': clip('Walk', [curve(ROOT, 0)], slot)}
    target = Target(original_anim())
    fake = NS(data=NS(actions=actions),
              app=NS(timers=NS(is_registered=lambda _f: True, register=lambda *a, **k: None)),
              context=NS(window_manager=wm, temp_override=lambda **_kw: nullcontext()),
              ops=NS(screen=NS(animation_cancel=lambda **_kw: playing.append(False),
                               animation_play=lambda: playing.append(True))))
    monkeypatch.setattr(preview, 'bpy', fake)
    monkeypatch.setattr(preview, '_session', None)
    monkeypatch.setattr(catalog, 'selected_target', lambda _context: target)
    context = NS(window=window, area=area, window_manager=wm,
                 view_layer=NS(objects=NS(active=target)))
    return NS(context=context, target=target, scene=s, window=window, state=state,
              actions=actions, playing=playing, area=area)


def test_clip_switch_keeps_the_original_snapshot_and_stop_restores_it(env):
    target = env.target
    preview.start(env.context, 'Wave', 11)
    first = preview.current()
    assert target.animation_data.action is env.actions['Wave']
    assert env.window.scene is env.scene  # no scene swap, ever
    target.pose.bones['Arm.L'].rotation_euler[1] = 1.3  # the clip evaluated
    preview.start(env.context, 'Walk', 11)
    second = preview.current()
    assert second is not first and second.snapshot is first.snapshot
    assert second.snapshot.values[(ARM, 1)] == 0.0  # never re-snapshotted
    assert target.animation_data.action is env.actions['Walk']
    target.pose.bones['Root'].location[0] = 1.0
    preview.stop()
    assert preview.current() is None
    assert target.animation_data == original_anim()
    assert target.pose.bones['Arm.L'].rotation_euler == [0, 0, 0]
    assert target.pose.bones['Root'].location == [0, 0, 0]
    assert (env.scene.frame_current, env.scene.frame_subframe) == (7, .25)
    assert env.state.preview_name == '' and not env.state.playing


def test_refusals_happen_before_any_change(env):
    env.target.animation_data.use_tweak_mode = True
    with pytest.raises(ValueError, match='tweak mode'):
        preview.start(env.context, 'Wave', 11)
    env.target.animation_data.use_tweak_mode = False
    env.area.type = 'IMAGE_EDITOR'
    with pytest.raises(ValueError, match='3D viewport'):
        preview.start(env.context, 'Wave', 11)
    assert preview.current() is None and env.scene.calls == []
    assert env.target.animation_data == original_anim()


def test_failed_start_restores_and_leaves_no_session(env, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError('evaluation failed')
    env.scene.frame_set = boom
    with pytest.raises(RuntimeError):
        preview.start(env.context, 'Wave', 11)
    assert preview.current() is None
    assert env.target.animation_data == original_anim()


def test_stop_clears_the_session_even_when_the_target_was_deleted(env, monkeypatch):
    preview.start(env.context, 'Wave', 11)

    class Deleted:
        def __getattr__(self, _name):
            raise ReferenceError('StructRNA of type Object has been removed')
    preview.current().target = Deleted()
    preview.stop()
    assert preview.current() is None
    assert env.scene.frame_current == 7  # the frame is still restored
    preview.start(env.context, 'Wave', 11)

    def deleted(*_args):
        raise ReferenceError('removed')
    monkeypatch.setattr(snapshots, 'restore', deleted)
    preview.stop()
    assert preview.current() is None
    preview.stop()  # idempotent


def test_hide_rig_hides_the_real_rig_and_stop_restores_visibility_and_selection(env):
    preview.start(env.context, 'Wave', 11)
    env.state.hide_rig = True
    preview.update_rig_visibility()
    assert env.target.hidden and not env.target.selected
    env.state.hide_rig = False
    preview.update_rig_visibility()
    assert not env.target.hidden
    env.state.hide_rig = True
    preview.update_rig_visibility()
    preview.stop()
    assert not env.target.hidden and env.target.selected


def test_closed_host_window_stops_without_touching_stale_window(env):
    preview.start(env.context, 'Wave', 11)
    preview.bpy.context.window_manager.windows = []  # the window was closed
    assert preview.host() == (None, None)
    assert preview._tick() is None
    assert preview.current() is None
    assert env.target.animation_data == original_anim()
