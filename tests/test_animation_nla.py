# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The browser's NLA layer: which Blender NLA RNA and screen operators run,
with what arguments, in what order. bpy is a MagicMock in the suite, so the
NLA data is a small fake that mirrors the RNA semantics the layer relies on
(``NlaTrack.is_solo`` clears the other tracks, ``strips.new`` starts the strip
at the given frame)."""
import ast
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.workflow.core import animation_catalog as catalog
from mixar.modules.workflow.core import animation_nla as nla

WORKFLOW = Path(__file__).parents[1] / 'src/scripts/mixar/modules/workflow'
ARM = 'pose.bones["Arm"].rotation_euler'


def curve(path=ARM, start=1, end=49):
    return NS(data_path=path, array_index=1, keyframe_points=[1, 2], sampled_points=[],
              range=lambda: (start, end))


def clip(name, start=1, end=49, slots=1):
    handles = [NS(handle=10 + i, target_id_type='OBJECT', name_display=f'Slot {i}')
               for i in range(slots)]
    return NS(name=name, slots=handles, use_frame_range=False, frame_range=(start, end),
              layers=[NS(strips=[NS(channelbags=[
                  NS(slot_handle=s.handle, fcurves=[curve(start=start, end=end)])
                  for s in handles])])])


class Strip:
    """A clip strip; ``action_slot`` counts its assignments, which is how the
    layer asks Blender to rebuild depsgraph relations after a solo/mute."""

    def __init__(self, name, start, action):
        first, last = catalog.clip_range(action, catalog.curves(action, action.slots[0]))
        self.type, self.name, self.action = 'CLIP', name, action
        self.frame_start, self.frame_end = float(start), float(start + last - first)
        self._slot, self.slot_sets = action.slots[0], 0

    @property
    def action_slot(self):
        return self._slot

    @action_slot.setter
    def action_slot(self, slot):
        self._slot, self.slot_sets = slot, self.slot_sets + 1


class Strips(list):
    def new(self, name, start, action):
        strip = Strip(name, start, action)
        self.append(strip)
        return strip


class Track:
    def __init__(self, anim, name, strips=()):
        self.anim, self.name, self.mute, self.solo = anim, name, False, False
        self.strips = Strips(strips)

    @property
    def is_solo(self):
        return self.solo

    @is_solo.setter
    def is_solo(self, value):  # rna_NlaTrack_solo_set
        for other in self.anim.nla_tracks:
            other.solo = False
        self.solo = value


class Tracks(list):
    def __init__(self, anim):
        super().__init__()
        self.anim = anim

    def new(self):
        track = Track(self.anim, 'NlaTrack')
        self.append(track)
        return track

    def get(self, name):
        return next((t for t in self if t.name == name), None)


class Rig:
    def __init__(self, active=None, use_nla=True):
        self.name, self.type, self.id_type = 'Rig', 'ARMATURE', 'OBJECT'
        self.pose = NS(bones={'Arm': NS(rotation_euler=[0.0, 0.0, 0.0])})
        self.animation_data = None
        self.hidden = False
        if active is not None:
            anim = self.animation_data_create()
            anim.action, anim.action_slot, anim.use_nla = active, active.slots[0], use_nla

    def path_resolve(self, path):
        return eval('self.' + path, {'self': self})

    def animation_data_create(self):
        if self.animation_data is None:
            self.animation_data = NS(action=None, action_slot=None, use_nla=True,
                                     use_tweak_mode=False)
            self.animation_data.nla_tracks = Tracks(self.animation_data)
        return self.animation_data

    def stored(self, action, name, start=1):
        track = self.animation_data_create().nla_tracks.new()
        track.name = name
        track.strips.new(action.name, start, action)
        return track

    def hide_get(self, view_layer=None):
        return self.hidden

    def hide_set(self, value, view_layer=None):
        self.hidden = value


@pytest.fixture
def blender(monkeypatch):
    calls = []
    window = NS(screen=NS(is_animation_playing=False), name='window')

    @contextmanager
    def temp_override(**kw):
        calls.append(('override', kw))
        yield

    def op(name, playing=None):
        def run(**kw):
            calls.append((name, kw))
            if playing is not None:
                window.screen.is_animation_playing = playing
        return run

    screen = NS(animation_play=op('animation_play', True),
                animation_cancel=op('animation_cancel', False),
                frame_jump=op('frame_jump'))
    monkeypatch.setattr(nla, 'bpy', NS(context=NS(temp_override=temp_override),
                                       ops=NS(screen=screen)))
    scene = NS(session_uid=7, use_preview_range=False, frame_preview_start=1,
               frame_preview_end=250, objects={})
    state = NS(play_target='', range_saved=False, range_scene=0, range_use=False,
               range_start=0, range_end=0)
    return NS(calls=calls, window=window, scene=scene, state=state)


def ops(calls):
    return [name for name, _kw in calls if name != 'override']


def play(env, rig, action, track='', strip=''):
    env.scene.objects[rig.name] = rig
    nla.play(env.window, env.scene, env.state, rig, action, action.slots[0], track, strip)


def test_play_solos_an_existing_strip_sets_its_range_and_plays(blender):
    idle, wave = clip('Idle'), clip('Wave', 1, 49)
    rig = Rig(idle)
    rig.stored(wave, 'Wave stored', start=101)
    play(blender, rig, wave, 'Wave stored', 'Wave')
    track = rig.animation_data.nla_tracks.get('Wave stored')
    assert track.is_solo and len(rig.animation_data.nla_tracks) == 1
    # The active action stays assigned; Blender mutes the action line under solo.
    assert rig.animation_data.action is idle
    s = blender.scene
    assert (s.use_preview_range, s.frame_preview_start, s.frame_preview_end) == (True, 101, 149)
    # Play first so animation_cancel later returns to the user's frame.
    assert ops(blender.calls) == ['animation_play', 'frame_jump']
    assert ('frame_jump', {'end': False}) in blender.calls
    assert ('override', {'window': blender.window}) in blender.calls
    assert blender.state.play_target == 'Rig'


def test_play_adds_a_clip_from_the_file_as_a_track_at_its_own_range(blender):
    rig, jump = Rig(clip('Idle')), clip('Jump', 5, 30, slots=2)
    blender.scene.frame_current = 80
    env = blender
    env.scene.objects['Rig'] = rig
    nla.play(env.window, env.scene, env.state, rig, jump, jump.slots[1])
    track = rig.animation_data.nla_tracks[0]
    strip = track.strips[0]
    assert (track.name, strip.name, strip.frame_start) == ('Jump', 'Jump', 5.0)
    assert strip.action_slot is jump.slots[1] and track.is_solo
    assert (env.scene.frame_preview_start, env.scene.frame_preview_end) == (5, 30)


def relation_rebuilds(rig):
    return sum(s.slot_sets for t in rig.animation_data.nla_tracks for s in t.strips)


def test_every_solo_or_mute_change_rebuilds_depsgraph_relations(blender):
    """Muted tracks are left out of the depsgraph; the is_solo/mute RNA setters
    don't tag a rebuild, so a rig with no active action never followed the
    soloed clip during playback (its frame counter ran, its pose did not)."""
    wave = clip('Wave')
    rig = Rig()
    rig.stored(wave, 'Wave').mute = True
    rig.stored(clip('Walk'), 'Walk').mute = True
    strip = rig.animation_data.nla_tracks[0].strips[0]
    play(blender, rig, wave, 'Wave', 'Wave')
    assert rig.animation_data.nla_tracks[0].is_solo
    assert relation_rebuilds(rig) == 1 and strip.action_slot is wave.slots[0]
    nla.stop(blender.window, blender.scene, blender.state)
    assert relation_rebuilds(rig) == 2
    nla.toggle_solo(rig, 'Walk', 'Walk')
    nla.toggle_mute(rig, 'Walk', 'Walk')
    assert relation_rebuilds(rig) == 4
    # No solo to clear: nothing changed, so no rebuild.
    nla.stop(blender.window, blender.scene, blender.state)
    assert relation_rebuilds(rig) == 4


def test_play_turns_nla_evaluation_on(blender):
    wave = clip('Wave')
    rig = Rig(clip('Idle'), use_nla=False)
    rig.stored(wave, 'Wave')
    play(blender, rig, wave, 'Wave', 'Wave')
    assert rig.animation_data.use_nla is True


def test_switching_clips_keeps_playing_and_the_first_saved_range(blender):
    walk, wave = clip('Walk', 1, 25), clip('Wave', 1, 49)
    rig = Rig(clip('Idle'))
    rig.stored(walk, 'Walk')
    rig.stored(wave, 'Wave')
    blender.scene.use_preview_range, blender.scene.frame_preview_end = True, 90
    play(blender, rig, walk, 'Walk', 'Walk')
    play(blender, rig, wave, 'Wave', 'Wave')
    tracks = rig.animation_data.nla_tracks
    assert [t.is_solo for t in tracks] == [False, True]
    assert ops(blender.calls) == ['animation_play', 'frame_jump', 'frame_jump']
    assert (blender.state.range_use, blender.state.range_end) == (True, 90)


def test_stop_cancels_clears_solo_and_restores_the_preview_range(blender):
    wave = clip('Wave')
    rig = Rig(clip('Idle'))
    rig.stored(wave, 'Wave')
    play(blender, rig, wave, 'Wave', 'Wave')
    blender.calls.clear()
    assert nla.is_playing(blender.window, blender.scene, blender.state)
    nla.stop(blender.window, blender.scene, blender.state)
    assert ops(blender.calls) == ['animation_cancel']
    assert ('animation_cancel', {}) in blender.calls  # restore_frame: Blender default
    assert not rig.animation_data.nla_tracks[0].is_solo
    s = blender.scene
    assert (s.use_preview_range, s.frame_preview_start, s.frame_preview_end) == (False, 1, 250)
    assert not nla.is_playing(blender.window, blender.scene, blender.state)


def test_switching_to_another_objects_clip_unsolos_the_first(blender):
    wave = clip('Wave')
    first, second = Rig(clip('Idle')), Rig(clip('Idle'))
    second.name = 'Other'
    first.stored(wave, 'Wave')
    second.stored(wave, 'Wave')
    play(blender, first, wave, 'Wave', 'Wave')
    play(blender, second, wave, 'Wave', 'Wave')
    assert not first.animation_data.nla_tracks[0].is_solo
    assert second.animation_data.nla_tracks[0].is_solo
    assert (blender.state.play_target, blender.state.range_end) == ('Other', 250)
    nla.stop(blender.window, blender.scene, blender.state)
    assert not second.animation_data.nla_tracks[0].is_solo
    assert blender.scene.frame_preview_end == 250 and not blender.scene.use_preview_range


def test_stop_always_ends_playback_but_leaves_tweak_mode_solo(blender):
    wave = clip('Wave')
    rig = Rig(clip('Idle'))
    rig.stored(wave, 'Wave')
    play(blender, rig, wave, 'Wave', 'Wave')
    rig.animation_data.use_tweak_mode = True
    nla.stop(blender.window, blender.scene, blender.state)
    assert not blender.window.screen.is_animation_playing
    assert rig.animation_data.nla_tracks[0].is_solo
    assert not blender.scene.use_preview_range


def test_playing_the_active_action_clears_solo_and_uses_its_range(blender):
    idle, wave = clip('Idle', 1, 61), clip('Wave')
    rig = Rig(idle)
    rig.stored(wave, 'Wave').is_solo = True
    play(blender, rig, idle)
    assert not rig.animation_data.nla_tracks[0].is_solo
    assert len(rig.animation_data.nla_tracks) == 1
    assert (blender.scene.frame_preview_start, blender.scene.frame_preview_end) == (1, 61)


def test_pause_toggles_native_playback_without_restoring_the_frame(blender):
    nla.pause(blender.window)
    blender.window.screen.is_animation_playing = True
    nla.pause(blender.window)
    assert ops(blender.calls) == ['animation_play', 'animation_cancel']
    assert ('animation_cancel', {'restore_frame': False}) in blender.calls


def test_solo_mute_add_and_delete_are_nla_track_edits(blender):
    walk, jump = clip('Walk'), clip('Jump')
    rig = Rig(clip('Idle'))
    rig.stored(walk, 'Walk')
    nla.toggle_solo(rig, 'Walk', 'Walk')
    nla.toggle_mute(rig, 'Walk', 'Walk')
    track = rig.animation_data.nla_tracks[0]
    assert track.is_solo and track.mute
    nla.add(rig, jump, jump.slots[0])
    nla.add(rig, jump, jump.slots[0])  # already on the target: no second track
    added = rig.animation_data.nla_tracks.get('Jump')
    assert len(rig.animation_data.nla_tracks) == 2 and not added.is_solo
    added.strips.new('Jump.001', 60, jump)
    nla.delete(rig, 'Jump', 'Jump.001')
    assert [s.name for s in added.strips] == ['Jump']
    nla.delete(rig, 'Walk', 'Walk')
    # The soloed track's solo is cleared before nla_tracks.remove(), which
    # keeps the AnimData solo flag set otherwise.
    assert not track.solo and [t.name for t in rig.animation_data.nla_tracks] == ['Jump']
    assert ops(blender.calls) == []


def test_hide_rig_is_a_plain_view_layer_toggle():
    rig, layer = Rig(), object()
    nla.toggle_rig_visibility(rig, layer)
    assert rig.hidden
    nla.toggle_rig_visibility(rig, layer)
    assert not rig.hidden


@pytest.mark.parametrize('case', ['incompatible', 'tweak', 'missing', 'no_target'])
def test_refused_clips_change_nothing(blender, case):
    wave = clip('Wave')
    rig = Rig(clip('Idle'))
    rig.stored(wave, 'Wave')
    args = (rig, wave, 'Wave', 'Wave')
    if case == 'incompatible':
        args = (rig, clip('Fly'), '', '')
        args[1].layers[0].strips[0].channelbags[0].fcurves = [curve('pose.bones["Wing"].scale')]
    elif case == 'tweak':
        rig.animation_data.use_tweak_mode = True
    elif case == 'missing':
        args = (rig, wave, 'Gone', 'Wave')
    else:
        args = (None, wave, '', '')
    before = [(t.name, t.solo, t.mute, len(t.strips)) for t in rig.animation_data.nla_tracks]
    with pytest.raises(ValueError):
        nla.play(blender.window, blender.scene, blender.state, args[0], args[1],
                 args[1].slots[0], args[2], args[3])
    assert [(t.name, t.solo, t.mute, len(t.strips))
            for t in rig.animation_data.nla_tracks] == before
    assert not blender.scene.use_preview_range and not blender.state.range_saved
    assert blender.calls == []


def _classes(path):
    tree = ast.parse(path.read_text())
    return tree, {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def test_every_data_change_is_one_undoable_operator():
    path = WORKFLOW / 'ui/operators/animations.py'
    tree, classes = _classes(path)
    edit = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                and node.targets[0].id == '_EDIT')
    assert {'REGISTER', 'UNDO'} <= set(ast.literal_eval(edit))
    for name in ('play', 'add', 'solo', 'mute', 'delete', 'stop', 'hide_rig'):
        body = classes[f'MIXAR_OT_animation_{name}'].body
        options = next(n.value for n in body if isinstance(n, ast.Assign)
                       and n.targets[0].id == 'bl_options')
        assert isinstance(options, ast.Name) and options.id == '_EDIT', name
    source = path.read_text()
    assert 'MIXAR_OT_animation_preview_controls' not in source
    assert 'MIXAR_OT_animations_open' not in source
    assert 'modal_handler_add' not in source
    assert 'tip_("Wait for the render to finish")' in source
    assert 'tip_("Switch to Object Mode to play animations")' in source


def test_no_animation_logic_of_our_own_remains():
    core = WORKFLOW / 'core'
    assert not (core / 'animation_preview.py').exists()
    assert not (core / 'animation_snapshot.py').exists()
    for name in ('animation_nla.py', 'animation_browser.py'):
        source = (core / name).read_text()
        for banned in ('.frame_set(', 'save_pre', 'undo_pre', 'path_resolve'):
            assert banned not in source, (name, banned)
        # The clip is never assigned to the action slot: that was the old preview.
        assert not re.search(r'\.action\s*=(?!=)', source), name
    assert 'bpy.app.timers' not in (core / 'animation_nla.py').read_text()
