# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A retarget result lands ON the rigged character.

The clip-only GLB imports as a bare armature carrying one action per preset
(the first active, every one stashed on a locked, muted NLA track). The
merge moves each action — with its slot — onto the original stamped
armature as a track named after the clip, makes the newest clip active, sets
the scene range to it and deletes the import. Bone-name matching is the
gate: nothing in common means the import is kept and the user told.

Data-model fakes here; the real Blender 5.2 API (slots, strips, removal) is
exercised by ``tests/qa/animation_merge_blender_smoke.py`` inside the app.
"""

import sys
from types import SimpleNamespace as NS

import pytest

from mixar.modules.hunyuan.constants import ANIMATE_RIG_JOB_PROP
from mixar.modules.hunyuan.core import animation_merge as merge


# --------------------------------------------------------------------------- #
# Fakes mirroring the slotted-action data model
# --------------------------------------------------------------------------- #

_pointers = iter(range(1, 10_000))


class _Action:
    def __init__(self, name, bones, start=1.0, end=24.0):
        self.name, self.users, self.use_fake_user = name, 0, False
        self._pointer = next(_pointers)
        self.frame_range = (start, end)
        self.slot = NS(handle=self._pointer, identifier=f"OB{name}")
        self.slots = [self.slot]
        bag = NS(slot_handle=self.slot.handle, fcurves=[
            NS(data_path=f'pose.bones["{bone}"].location') for bone in bones])
        self.layers = [NS(strips=[NS(channelbags=[bag])])]

    def as_pointer(self):
        return self._pointer


class _Strips(list):
    def new(self, name, start, action):
        strip = NS(name=name, action=action, action_slot=None, start=start)
        action.users += 1
        self.append(strip)
        return strip


class _Tracks(list):
    def new(self):
        track = NS(name="", strips=_Strips(), lock=False, mute=False)
        self.append(track)
        return track


class _AnimData:
    def __init__(self):
        self._action, self.action_slot, self.nla_tracks = None, None, _Tracks()

    @property
    def action(self):
        return self._action

    @action.setter
    def action(self, value):
        if self._action is not None:
            self._action.users -= 1
        if value is not None:
            value.users += 1
        self._action = value


class _Object:
    def __init__(self, name, type, bones=(), parent=None, **stamps):
        self.name, self.type, self.parent = name, type, parent
        self.data = NS(bones=[NS(name=b) for b in bones], users=1, name=name)
        self.animation_data = None
        self.children_recursive, self.modifiers = [], []
        self._props = dict(stamps)
        self._pointer = next(_pointers)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def animation_data_create(self):
        self.animation_data = _AnimData()
        return self.animation_data

    def as_pointer(self):
        return self._pointer


def _imported(*clips):
    """A clip armature the way the glTF importer leaves it."""
    arm = _Object("Armature.001", 'ARMATURE', bones=["Hip", "L_Thigh"])
    anim = arm.animation_data_create()
    for action in clips:
        track = anim.nla_tracks.new()
        track.name = action.name
        strip = track.strips.new(action.name, 1, action)
        strip.action_slot = action.slot
        track.lock = track.mute = True
    if clips:
        anim.action, anim.action_slot = clips[0], clips[0].slot
    return arm


def _rig():
    return _Object("Rig", 'ARMATURE', bones=["Root", "Hip", "L_Thigh", "R_Thigh"],
                   **{ANIMATE_RIG_JOB_PROP: "job-1"})


# --------------------------------------------------------------------------- #
# Reading the import
# --------------------------------------------------------------------------- #


def test_clips_are_read_in_file_order_without_the_active_duplicate():
    walk, idle = _Action("walk", ["Hip"]), _Action("idle", ["Hip"], end=60.0)
    arm = _imported(walk, idle)
    clips = merge.imported_clips([arm])
    assert [action.name for action, _slot, _binding in clips] == ["walk", "idle"]
    assert [slot is action.slot for action, slot, _b in clips] == [True, True]
    assert merge.clip_bone_names(clips[0][2]) == {"Hip"}


def test_the_rig_is_found_by_stamp_then_by_name():
    rig, other = _rig(), _Object("Other", 'ARMATURE')
    mesh = _Object("Rig", 'MESH')  # a mesh wearing the name is not a rig
    scene = NS(objects=NS(__iter__=lambda s: iter([other, rig]), get=lambda n: {
        "Other": other}.get(n)))
    scene.objects = _Objects([other, rig])
    assert merge.rig_armature(scene, "job-1") is rig
    assert merge.rig_armature(scene, "job-2", "Other") is other
    assert merge.rig_armature(_Scene([mesh]), "job-2", "Rig") is None


class _Objects(list):
    def get(self, name):
        return next((o for o in self if o.name == name), None)


class _Scene:
    def __init__(self, objects):
        self.objects = _Objects(objects)
        self.frame_start, self.frame_end, self.frame_current = 1, 250, 1


def test_the_rig_the_job_was_enqueued_for_wins_over_a_stamped_duplicate():
    # Shift+D copies the stamps: the original and its duplicate both carry
    # job-1, and the duplicate may come first in the scene.
    original, duplicate = _rig(), _rig()
    duplicate.name = "Rig.001"
    scene = _Scene([original, duplicate])
    assert merge.rig_armature(scene, "job-1", "Rig.001") is duplicate
    assert merge.rig_armature(scene, "job-1", "Rig") is original
    # The target renamed meanwhile: any armature with the stamp.
    assert merge.rig_armature(scene, "job-1", "Renamed") is original
    # The named armature carries another job's stamp: the stamped one wins.
    other = _Object("Other", 'ARMATURE', **{ANIMATE_RIG_JOB_PROP: "job-2"})
    assert merge.rig_armature(_Scene([other, original]), "job-1", "Other") is original
    # Excluded names never qualify, even with the right stamp.
    assert merge.rig_armature(scene, "job-1", "Rig.001", exclude=["Rig.001"]) is original


def test_the_character_is_labelled_by_its_mesh_not_the_generic_armature():
    rig = _rig()
    rig.name = "Armature"
    body, cape = _Object("Hero.001", 'MESH', parent=rig), _Object("Cape", 'MESH')
    bone_empty = _Object("Socket", 'EMPTY', parent=rig)
    rig.children_recursive = [bone_empty, body]
    assert merge.character_label(_Scene([rig, bone_empty, body, cape]), rig) == "Hero.001"
    cape.modifiers = [NS(type='ARMATURE', object=rig)]
    rig.children_recursive = [bone_empty]
    assert merge.character_label(_Scene([rig, bone_empty, cape]), rig) == "Cape"
    assert merge.character_label(_Scene([rig]), rig) == "Armature"


# --------------------------------------------------------------------------- #
# The merge
# --------------------------------------------------------------------------- #


def test_clips_move_onto_the_rig_as_stashed_tracks_with_the_newest_active(monkeypatch):
    removed = []
    monkeypatch.setattr(merge, "remove_objects", lambda objects: removed.extend(objects))
    walk, idle = _Action("walk", ["Hip", "L_Thigh"]), _Action("idle", ["Hip"], 0.0, 15.3)
    rig, arm = _rig(), _imported(walk, idle)
    scene = _Scene([rig, arm])

    assert merge.merge_clips_onto_rig(scene, [arm], rig) == (["walk", "idle"], [])

    anim = rig.animation_data
    assert [(t.name, t.lock, t.mute) for t in anim.nla_tracks] == [
        ("walk", True, True), ("idle", True, True)]
    assert [(t.strips[0].action, t.strips[0].action_slot) for t in anim.nla_tracks] == [
        (walk, walk.slot), (idle, idle.slot)]
    assert anim.action is idle and anim.action_slot is idle.slot
    assert (scene.frame_start, scene.frame_end, scene.frame_current) == (0, 16, 0)
    assert removed == [arm]


def test_a_clip_with_no_bone_in_common_leaves_the_import_alone(monkeypatch):
    monkeypatch.setattr(merge, "remove_objects", lambda objects: pytest.fail("must not delete"))
    foreign = _Action("walk", ["tripo::0_Left_Limb_0"])
    rig, arm = _rig(), _imported(foreign)
    assert merge.merge_clips_onto_rig(_Scene([rig, arm]), [arm], rig) == ([], ["walk"])
    assert rig.animation_data is None


def test_a_clip_that_fits_nothing_is_dropped_beside_the_ones_that_merge(monkeypatch):
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    walk, foreign = _Action("walk", ["Hip"]), _Action("crawl", ["tripo::0_Left_Limb_0"])
    rig, arm = _rig(), _imported(walk, foreign)

    merged, dropped = merge.merge_clips_onto_rig(_Scene([rig, arm]), [arm], rig)

    assert (merged, dropped) == (["walk"], ["crawl"])
    assert [t.name for t in rig.animation_data.nla_tracks] == ["walk"]


def test_an_unstashed_user_action_is_parked_before_the_new_clip_takes_over(monkeypatch):
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    rig = _rig()
    mine = _Action("my_pose", ["Hip"])
    rig.animation_data_create().action = mine
    arm = _imported(_Action("walk", ["Hip"]))
    merge.merge_clips_onto_rig(_Scene([rig, arm]), [arm], rig)
    assert [t.name for t in rig.animation_data.nla_tracks] == ["my_pose", "walk"]
    assert rig.animation_data.action.name == "walk"


def test_removal_drops_objects_and_the_orphan_data_and_actions(monkeypatch):
    calls = []
    unused = _Action("unused", ["Hip"])
    arm = _imported(unused)
    arm.animation_data.action = None  # only the strip holds it
    arm.animation_data.nla_tracks[0].strips[0].action.users = 0
    armatures = NS(get=lambda n: arm.data if n == arm.data.name else None,
                   remove=lambda d: calls.append(("armature", d.name)))
    fake_bpy = NS(data=NS(
        objects=NS(remove=lambda o, do_unlink=True: calls.append(("object", o.name))),
        armatures=armatures, meshes=NS(get=lambda n: None),
        actions=NS(remove=lambda a: calls.append(("action", a.name))),
    ))
    arm.data.users = 0
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    assert merge.remove_objects([arm]) == 1
    assert calls == [("object", "Armature.001"), ("armature", "Armature.001"),
                     ("action", "unused")]


# --------------------------------------------------------------------------- #
# The job hook
# --------------------------------------------------------------------------- #


def test_clips_follow_the_result_order_not_the_importers_track_order(monkeypatch):
    # Blender 5.2's glTF importer stashes the tracks in REVERSE file order and
    # renames a clip whose name is taken ("walk" on a rig that has a walk).
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    idle, walk = _Action("idle", ["Hip"], 0.0, 368.0), _Action("walk.001", ["Hip"])
    wave = _Action("wave_goodbye_01", ["Hip"], 0.0, 158.0)
    rig, arm = _rig(), _imported(wave, walk, idle)
    scene = _Scene([rig, arm])

    names, _dropped = merge.merge_clips_onto_rig(
        scene, [arm], rig, ["idle", "walk", "wave_goodbye_01"])

    assert names == ["idle", "walk", "wave_goodbye_01"]
    assert rig.animation_data.action is wave
    assert (scene.frame_start, scene.frame_end) == (0, 158)


def test_a_clip_named_after_its_whole_preset_lands_under_its_short_name(monkeypatch):
    # Tripo v2.5 (creature rigs) names a single clip by the whole preset.
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    walk = _Action("preset:quadruped:walk", ["Hip"])
    rig, arm = _rig(), _imported(walk)

    assert merge.merge_clips_onto_rig(_Scene([rig, arm]), [arm], rig, ["walk"]) == (["walk"], [])
    assert walk.name == "walk" and rig.animation_data.nla_tracks[0].name == "walk"


def test_a_clip_the_rig_already_has_gets_a_numbered_track(monkeypatch):
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    rig = _rig()
    first = _Action("walk", ["Hip"])
    merge.merge_clips_onto_rig(_Scene([rig]), [_imported(first)], rig, ["walk"])
    again = _Action("walk.001", ["Hip"])

    names, _dropped = merge.merge_clips_onto_rig(
        _Scene([rig]), [_imported(again)], rig, ["walk"])

    assert names == ["walk.001"]
    assert [t.name for t in rig.animation_data.nla_tracks] == ["walk", "walk.001"]


def test_without_an_order_the_import_order_stands():
    walk, idle = _Action("walk", ["Hip"]), _Action("idle", ["Hip"])
    clips = [(walk,), (idle,)]
    assert merge.order_clips(clips, ()) == clips
    assert merge.order_clips(clips, ["idle"]) == [(idle,), (walk,)]


@pytest.fixture
def hook_seams(monkeypatch):
    calls = NS(toasts=[], in_front=[], merged=[])
    store = NS(push=lambda kind, title, body="": calls.toasts.append((kind, title, body)))
    monkeypatch.setitem(sys.modules, "mixar.modules.common.notifications",
                        NS(get_notification_store=lambda: store))
    monkeypatch.setitem(sys.modules, "mixar.modules.common.job_queue.core.queue_download",
                        NS(resolve_job_scene=lambda name, session: calls.scene))
    import mixar.modules.hunyuan.core.animate_enqueue as enqueue

    monkeypatch.setattr(enqueue, "show_armatures_in_front",
                        lambda names: calls.in_front.append(names))
    return calls


def _bpy_with(scene, objects, monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", NS(
        data=NS(objects=_Objects(objects)), context=NS(scene=scene)))


def test_the_hook_returns_the_character_names_after_a_merge(hook_seams, monkeypatch):
    rig = _rig()
    body, cape = _Object("Body", 'MESH', parent=rig), _Object("Cape", 'MESH')
    cape.modifiers = [NS(type='ARMATURE', object=rig)]
    rig.children_recursive = [body]
    arm = _imported(_Action("walk", ["Hip"]))
    hook_seams.scene = _Scene([rig, body, cape, arm])
    _bpy_with(hook_seams.scene, [rig, body, cape, arm], monkeypatch)
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    merged = []
    hook = merge.merge_hook("job-1", "Rig", on_merged=lambda job, names: merged.append(names))
    job = NS(scene_name="Scene", agent_ref={"session_id": "s"})

    assert hook(job, "Armature.001") == "Rig, Body, Cape"
    assert merged == [["Rig", "Body", "Cape"]]
    assert hook_seams.toasts == [] and hook_seams.in_front == []


@pytest.mark.parametrize("rig_present, body", [
    (False, merge.RIG_GONE_BODY), (True, merge.NO_MATCH_BODY),
])
def test_the_hook_keeps_the_import_and_says_so_when_it_cannot_merge(
        hook_seams, monkeypatch, rig_present, body):
    arm = _imported(_Action("walk", ["tripo::0_Left_Limb_0"]))
    objects = [arm] + ([_rig()] if rig_present else [])
    hook_seams.scene = _Scene(objects)
    _bpy_with(hook_seams.scene, objects, monkeypatch)
    monkeypatch.setattr(merge, "remove_objects", lambda objects: pytest.fail("kept"))
    hook = merge.merge_hook("job-1", "Rig", on_merged=lambda *a: pytest.fail("no merge"))

    assert hook(NS(scene_name="Scene", agent_ref=None), "Armature.001") is None
    assert hook_seams.in_front == ["Armature.001"]
    assert hook_seams.toasts == [("warning", merge.RIG_GONE_TITLE, body)]


def test_the_hook_warns_when_some_clips_did_not_fit(hook_seams, monkeypatch):
    rig = _rig()
    arm = _imported(_Action("walk", ["Hip"]), _Action("crawl", ["tripo::0_Left_Limb_0"]))
    hook_seams.scene = _Scene([rig, arm])
    _bpy_with(hook_seams.scene, [rig, arm], monkeypatch)
    monkeypatch.setattr(merge, "remove_objects", lambda objects: None)
    hook = merge.merge_hook("job-1", "Rig")

    assert hook(NS(scene_name="Scene", agent_ref=None), "Armature.001") == "Rig"
    assert hook_seams.toasts == [("warning", merge.PARTLY_MERGED_TITLE,
                                  "crawl: no bone in common with the character's skeleton")]


def test_an_import_without_a_clip_is_removed_and_says_nothing_was_imported(
        hook_seams, monkeypatch):
    rig, arm = _rig(), _imported()
    hook_seams.scene = _Scene([rig, arm])
    _bpy_with(hook_seams.scene, [rig, arm], monkeypatch)
    removed = []
    monkeypatch.setattr(merge, "remove_objects", lambda objects: removed.extend(objects))
    hook = merge.merge_hook("job-1", "Rig", on_merged=lambda *a: pytest.fail("no merge"))

    assert hook(NS(scene_name="Scene", agent_ref=None), "Armature.001") is None
    assert removed == [arm] and rig.animation_data is None
    assert hook_seams.toasts == [("warning", merge.NOTHING_IMPORTED_TITLE,
                                  merge.NOTHING_IMPORTED_BODY)]


def test_an_import_that_took_the_deleted_rigs_name_is_kept_not_merged_into_itself(
        hook_seams, monkeypatch):
    # The rig "Rig" was deleted while the job ran; the clip import is then
    # named "Rig" too and must not be taken for the rig (live: it merged into
    # itself, deleted itself and raised "StructRNA ... has been removed").
    arm = _imported(_Action("walk", ["Hip"]))
    arm.name = "Rig"
    hook_seams.scene = _Scene([arm])
    _bpy_with(hook_seams.scene, [arm], monkeypatch)
    monkeypatch.setattr(merge, "remove_objects", lambda objects: pytest.fail("kept"))
    hook = merge.merge_hook("job-1", "Rig", on_merged=lambda *a: pytest.fail("no merge"))

    assert hook(NS(scene_name="Scene", agent_ref=None), "Rig") is None
    assert hook_seams.toasts == [("warning", merge.RIG_GONE_TITLE, merge.RIG_GONE_BODY)]
