# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Land a retarget result ON the rigged character instead of beside it.

A ``tripo_retarget`` job returns one clip-only GLB: the rig's skeleton with
one glTF animation per preset and no mesh. Blender's importer turns that into
a bare armature whose first clip is the active action and whose every clip is
stashed on a locked, muted NLA track. The merge moves those actions onto the
ORIGINAL armature — the one the rig job imported, found by its
``mixar_rig_job_id`` stamp — by bone name (the bone-name SET is the rig's; only
the order differs), stashes each as a track named after its clip, makes the
newest clip the active action, deletes the imported objects and their orphan
data, and sets the scene frame range to the active clip.

Blender 5 actions are slotted: an F-curve lives in the channelbag of the slot
the importer bound to ITS armature. Moving an action therefore means assigning
both the action and that slot (``action_slot``) on the target's AnimData and on
every stashed strip — an action assigned without its slot animates nothing.

When the original armature is gone (deleted, or the file changed), the import
is kept as it is and the user is told; nothing is deleted.
"""

from __future__ import annotations

import math
import re

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_
from mixar.modules.common.utils.animation import bound_fcurves
from ..constants import ANIMATE_RIG_JOB_PROP
from .animate_presets import clip_name

logger = get_logger(__name__)

_BONE_PATH = re.compile(r'^pose\.bones\["(.+?)"\]')


def rig_armature(scene, rig_job_id: str, fallback_name: str = ""):
    """The armature a rig job imported into *scene*, or None.

    Stamp first (the name may have changed since), then the name the job
    was enqueued with, provided it is still an armature.
    """
    objects = getattr(scene, "objects", ())
    for obj in objects:
        if obj.type == 'ARMATURE' and str(obj.get(ANIMATE_RIG_JOB_PROP, "")) == str(rig_job_id):
            return obj
    if fallback_name:
        obj = objects.get(fallback_name)
        if obj is not None and obj.type == 'ARMATURE':
            return obj
    return None


def character_object_names(armature) -> list:
    """The armature and everything parented under it (the character)."""
    names = [armature.name]
    for obj in getattr(armature, "children_recursive", ()):
        if obj.name not in names:
            names.append(obj.name)
    return names


def skinned_mesh_names(scene, armature) -> list:
    """Meshes deformed by *armature* that are not already its children."""
    return [
        obj.name for obj in scene.objects
        if obj.type == 'MESH' and obj.parent is not armature
        and any(m.type == 'ARMATURE' and m.object is armature for m in obj.modifiers)
    ]


def clip_bone_names(binding) -> set:
    """Bone names an action/slot binding animates (``pose.bones["X"]`` paths)."""
    names = set()
    for fcurve in bound_fcurves(binding):
        match = _BONE_PATH.match(getattr(fcurve, "data_path", "") or "")
        if match:
            names.add(match.group(1))
    return names


def imported_clips(objects) -> list:
    """``(action, slot, binding)`` per clip the import carries, in glTF order.

    The importer stashes every animation on an NLA track and also makes the
    first one active (a duplicate of a stashed one — deduplicated by action).
    The track order is the importer's (Blender 5.2 stashes in REVERSE file
    order), so the merge orders clips by the result's ``animations`` list
    (``order_clips``), never by this one.
    """
    clips, seen = [], set()

    def add(binding):
        action = getattr(binding, "action", None)
        if action is None or action.as_pointer() in seen:
            return
        seen.add(action.as_pointer())
        clips.append((action, getattr(binding, "action_slot", None), binding))

    for obj in objects:
        anim = getattr(obj, "animation_data", None)
        if anim is None:
            continue
        for track in anim.nla_tracks:
            for strip in track.strips:
                add(strip)
        add(anim)
    return clips


def _assign(binding, action, slot) -> None:
    binding.action = action
    if slot is not None:
        try:
            binding.action_slot = slot
        except Exception as error:  # noqa: BLE001 — a legacy (unslotted) action
            logger.debug("[Animate] slot assignment skipped: %s", error)


def stash_clip(anim, action, slot, name: str) -> str:
    """Park *action* on its own locked, muted NLA track; returns the track name.

    Blender uniquifies action and track names itself, so a clip that already
    exists on the rig ("walk") gets "walk.001" rather than replacing it.
    """
    action.name = name
    track = anim.nla_tracks.new()
    track.name = action.name
    start = int(math.floor(float(action.frame_range[0])))
    strip = track.strips.new(action.name, start, action)
    _assign(strip, action, slot)
    track.lock = True
    track.mute = True
    return track.name


def _on_a_track(anim, action) -> bool:
    return any(
        strip.action == action for track in anim.nla_tracks for strip in track.strips
    )


def set_frame_range(scene, action) -> None:
    start, end = (float(value) for value in action.frame_range)
    scene.frame_start = int(math.floor(start))
    scene.frame_end = max(scene.frame_start, int(math.ceil(end)))
    scene.frame_current = scene.frame_start


def remove_objects(objects) -> int:
    """Delete *objects* and the object data and actions nothing else uses."""
    import bpy

    datas = [obj.data for obj in objects if getattr(obj, "data", None) is not None]
    actions = [action for action, _slot, _binding in imported_clips(objects)]
    for obj in objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    removed = len(objects)
    for data in datas:
        if data.users == 0:
            for collection in (bpy.data.armatures, bpy.data.meshes):
                if collection.get(data.name) == data:
                    collection.remove(data)
                    break
    for action in actions:
        if action.users == 0 and not action.use_fake_user:
            bpy.data.actions.remove(action)
    return removed


_NAME_SUFFIX = re.compile(r"\.\d{3,}$")


def order_clips(clips, order) -> list:
    """*clips* (``(action, ...)`` tuples) in the result's ``animations`` order.

    The result lists short names ("walk"), while a clip may carry the whole
    preset (Tripo v2.5 names a single clip "preset:quadruped:walk") and the
    importer renames a clip whose name is taken ("walk.001"); both are
    ignored when matching. Unlisted clips keep their order after the rest.
    """
    rank = {str(name): index for index, name in enumerate(order or ())}
    if not rank:
        return list(clips)
    return sorted(clips, key=lambda clip: rank.get(
        clip_name(_NAME_SUFFIX.sub("", clip[0].name)), len(rank)))


def merge_clips_onto_rig(scene, imported, target, order=()) -> list:
    """Move the clips *imported* carries onto *target*; return the clip names.

    *order* is the job result's ``animations`` (request order): the tracks are
    stashed in it and its last clip — the newest — becomes the active action.
    An empty result means nothing matched the rig (no bone in common) and the
    import was left untouched — the caller keeps it and says so.
    """
    clips = imported_clips(imported)
    rig_bones = {bone.name for bone in target.data.bones}
    matched = [
        (action, slot) for action, slot, binding in order_clips(clips, order)
        if clip_bone_names(binding) & rig_bones
    ]
    if not matched:
        logger.warning("[Animate] no clip matches the rig's bones; import kept")
        return []
    anim = target.animation_data or target.animation_data_create()
    # A clip the user had active but never stashed must not be lost under the
    # new one. Our own merges always stash first, so this is their own work.
    if anim.action is not None and not _on_a_track(anim, anim.action):
        stash_clip(anim, anim.action, getattr(anim, "action_slot", None), anim.action.name)
    for _action, slot in matched:
        # The importer named the slot after ITS armature; naming it after the
        # rig lets Blender auto-pick it whenever the action is reassigned.
        try:
            slot.name_display = target.name
        except Exception:  # noqa: BLE001 — read-only on an older Blender, harmless
            pass
    # Tracks carry the short clip name, whatever the vendor named the clip.
    names = [stash_clip(anim, action, slot, clip_name(action.name)) for action, slot in matched]
    newest, newest_slot = matched[-1]
    _assign(anim, newest, newest_slot)
    set_frame_range(scene, newest)
    remove_objects(imported)
    logger.info("[Animate] merged %d clip(s) onto %s: %s", len(names), target.name, names)
    return names


# The sentence shown (toast + log) when the rig is gone and the import stays.
RIG_GONE_TITLE = n_("Animation imported on its own")
RIG_GONE_BODY = n_("The rigged character it was made for is no longer in the scene")
NO_MATCH_BODY = n_("Its skeleton does not match the rigged character, so it was kept beside it")


def merge_hook(rig_job_id: str, rig_name: str = "", on_merged=None):
    """``on_imported`` hook for a retarget job (see ``AsyncGLBJob``).

    Returns the ORIGINAL character's object names after a merge, so the job
    (and the agent result) names the character rather than the deleted clip
    armature; None keeps the imported names when the import stays.
    """
    def _hook(job, object_names: str):
        import bpy
        from mixar.modules.common.job_queue.core.queue_download import resolve_job_scene
        from mixar.modules.common.notifications import get_notification_store
        from .animate_enqueue import show_armatures_in_front

        session_id = str((getattr(job, "agent_ref", None) or {}).get("session_id") or "")
        scene = resolve_job_scene(getattr(job, "scene_name", ""), session_id) or bpy.context.scene
        names = [name.strip() for name in str(object_names or "").split(",") if name.strip()]
        imported = [obj for obj in (bpy.data.objects.get(name) for name in names) if obj]
        target = rig_armature(scene, rig_job_id, rig_name)
        order = (getattr(job, "result_data", None) or {}).get("animations") or ()
        clips = merge_clips_onto_rig(scene, imported, target, order) if target is not None else []
        if not clips:
            show_armatures_in_front(object_names)
            body = NO_MATCH_BODY if target is not None else RIG_GONE_BODY
            logger.warning("[Animate] %s", body)
            try:
                get_notification_store().push("warning", RIG_GONE_TITLE, body)
            except Exception:  # noqa: BLE001 — a toast must never fail a landed import
                pass
            return None
        character = character_object_names(target) + skinned_mesh_names(scene, target)
        if on_merged is not None:
            on_merged(job, character)
        return ", ".join(character)

    return _hook
