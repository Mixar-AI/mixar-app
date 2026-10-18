# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rigged characters (contract v1.3 §1, §3).

A CHARACTER is a ``player``, ``boss`` or ``enemy`` role node whose subtree
holds a skinned skeleton: an ARMATURE that deforms a mesh of the same
subtree (an Armature modifier pointing at it, or armature parenting). Its
clips are the ACTIONS on its rigs (active action and NLA strip actions —
never strip names: helper strips are literally called ``idle``/``walk``)
named ``<clip_prefix><state>``. ``classify`` maps a clip to its state;
``attack_*`` and ``light_*`` are families (one or more clips).

Pure attribute reads, no ``bpy`` import: the standalone suite drives this
with fakes, and the exporter, ``game_status`` and the Combat panel share it.
"""

from __future__ import annotations

import re

from ..constants import CHARACTER_ROLES, CLIP_STATES, DEFAULT_CLIP_PREFIX
from . import roles

FAMILIES = {"attack_*": re.compile(r"^attack_[A-Za-z0-9_]+$"), "light_*": re.compile(r"^light_[0-9]+$")}
# Clips whose combat window (hit or i-frames) the spec may carry.
COMBAT_STATES = ("attack_*", "light_*", "heavy", "dodge")


def clip_prefix(role: str, params: dict) -> str:
    return str((params or {}).get("clip_prefix") or DEFAULT_CLIP_PREFIX.get(role, ""))


def classify(clip: str, prefix: str, role: str) -> str | None:
    """The §3 state of ``clip`` for a character with ``prefix``, or None."""
    clip = str(clip or "")
    if not prefix or not clip.startswith(prefix):
        return None
    rest = clip[len(prefix):]
    for state in CLIP_STATES.get(role, ()):
        family = FAMILIES.get(state)
        if (family.match(rest) if family else rest == state):
            return state
    return None


def _deforms(mesh, armature) -> bool:
    if getattr(mesh, "type", "") != "MESH":
        return False
    if getattr(mesh, "parent", None) is armature and getattr(mesh, "parent_type", "") == "ARMATURE":
        return True
    return any(getattr(m, "type", "") == "ARMATURE" and getattr(m, "object", None) is armature
               for m in getattr(mesh, "modifiers", ()) or ())


def rigs(subtree) -> list:
    """ARMATUREs of ``subtree`` that deform one of its meshes (name order)."""
    meshes = [obj for obj in subtree if getattr(obj, "type", "") == "MESH"]
    found = [obj for obj in subtree if getattr(obj, "type", "") == "ARMATURE"
             and any(_deforms(mesh, obj) for mesh in meshes)]
    return sorted(found, key=lambda obj: obj.name)


def rig_actions(armatures) -> list:
    """Distinct Actions on ``armatures``: the active one and every NLA strip's."""
    found, seen = [], set()

    def add(action):
        name = getattr(action, "name", None)
        if name and name not in seen:
            seen.add(name)
            found.append(action)

    for obj in armatures:
        anim = getattr(obj, "animation_data", None)
        if anim is None:
            continue
        add(getattr(anim, "action", None))
        for track in getattr(anim, "nla_tracks", ()) or ():
            for strip in getattr(track, "strips", ()) or ():
                add(getattr(strip, "action", None))
    return found


def is_character_role(role) -> bool:
    return role in CHARACTER_ROLES


def describe(node, role: str, params: dict, subtree) -> dict:
    """``{object, role, rig, rigs, clip_prefix, clips: {state: [clip]},
    missing: [state], actions: {clip: Action}}`` for one role node.
    ``actions`` holds live objects for the exporter; reports drop it."""
    armatures = rigs(subtree)
    prefix = clip_prefix(role, params)
    clips, actions = {}, {}
    for action in rig_actions(armatures):
        state = classify(action.name, prefix, role)
        if state is None:
            continue
        clips.setdefault(state, []).append(action.name)
        actions[action.name] = action
    for names in clips.values():
        names.sort()
    return {
        "object": node.name, "role": role, "rig": bool(armatures),
        "rigs": [arm.name for arm in armatures], "clip_prefix": prefix,
        "clips": {state: clips[state] for state in CLIP_STATES.get(role, ()) if state in clips},
        "missing": [state for state in CLIP_STATES.get(role, ()) if state not in clips],
        "actions": actions,
    }


def find(objects, hierarchy=None) -> list[dict]:
    """``describe`` for every in-game player/boss/enemy role node of
    ``objects`` (name order); ``hierarchy`` defaults to one over ``objects``."""
    from .assemblies import Hierarchy
    hierarchy = hierarchy or Hierarchy(objects)
    found = []
    for obj in sorted(objects, key=lambda o: o.name):
        role = roles.get_role(obj)
        if not is_character_role(role) or not roles.in_game(obj):
            continue
        subtree = [obj] + [o for o in hierarchy.descendants(obj) if roles.in_game(o)]
        found.append(describe(obj, role, roles.get_params(obj), subtree))
    return found


def export_clips(found) -> list[str]:
    """The ``animations`` selection for a boss_fight GLB: every character's
    known-state clips, sorted. ``[]`` (no animation at all) when none."""
    return sorted({clip for character in found for names in character["clips"].values()
                   for clip in names})


def public(character: dict) -> dict:
    return {k: v for k, v in character.items() if k != "actions"}
