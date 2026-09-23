# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Assemble bone resolution on synthetic Mixamo, Rigify and Unreal A-pose rigs."""

import json
from pathlib import Path

import numpy as np
import pytest

from mixar.modules.moodboard.core.assemble_bones import (
    BoneInfo,
    bone_sockets,
    facing_yaw,
    normalize_bone_name,
    resolve_bones,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
HEIGHT = 1.85


def _load(name):
    rows = json.loads((FIXTURES / f"assemble_bones_{name}.json").read_text(encoding="utf-8"))
    return [BoneInfo(row["name"], np.array(row["head"], dtype=float),
                     np.array(row["tail"], dtype=float), row["parent"], row["deform"])
            for row in rows]


EXPECTED = {
    "mixamo": {
        "hand_r": "mixamorig:RightHand", "hand_l": "mixamorig:LeftHand",
        "forearm_r": "mixamorig:RightForeArm", "forearm_l": "mixamorig:LeftForeArm",
        "head": "mixamorig:Head", "chest": "mixamorig:Spine2", "hips": "mixamorig:Hips",
    },
    "rigify": {
        "hand_r": "DEF-hand.R", "hand_l": "DEF-hand.L",
        "forearm_r": "DEF-forearm.R", "forearm_l": "DEF-forearm.L",
        "head": "DEF-spine.006", "chest": "DEF-spine.003", "hips": "DEF-spine",
    },
    "ue": {
        "hand_r": "hand_r", "hand_l": "hand_l",
        "forearm_r": "lowerarm_r", "forearm_l": "lowerarm_l",
        "head": "head", "chest": "spine_03", "hips": "pelvis",
    },
}


@pytest.mark.parametrize("rig", sorted(EXPECTED))
def test_mixamo_rigify_ue_names_resolve_slots(rig):
    resolved = resolve_bones(_load(rig), HEIGHT)
    assert {key: name for key, (name, _how) in resolved.items()} == EXPECTED[rig]
    assert {how for _name, how in resolved.values()} == {"name"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mixamorig:RightHand", ("hand", "R")),
        ("mixamorig5:LeftForeArm", ("forearm", "L")),
        ("DEF-hand.L", ("hand", "L")),
        ("DEF-forearm.R.001", ("forearm", "R")),
        ("hand_r", ("hand", "R")),
        ("Hand_L", ("hand", "L")),
        ("L_Hand", ("hand", "L")),
        ("hand.R.001", ("hand", "R")),
        ("DEF-spine.003", ("spine3", "")),
        ("spine_03", ("spine3", "")),
        ("mixamorig:Spine2", ("spine2", "")),
        ("mixamorig:LeftHandThumb1", ("handthumb", "L")),
        ("mixamorig:HeadTop_End", ("headtopend", "")),
        ("ik_hand_l", ("ikhand", "L")),
    ],
)
def test_bone_names_normalise(name, expected):
    assert normalize_bone_name(name) == expected


def test_finger_and_end_bones_are_never_hands():
    # Rename the real hand and head bones to words no rule knows: only the
    # finger chains and HeadTop_End still say "hand" / "head" in their names.
    renamed = {"mixamorig:LeftHand": "mixamorig:LeftWrist",
               "mixamorig:RightHand": "mixamorig:RightWrist",
               "mixamorig:Head": "mixamorig:Skull"}
    bones = [bone._replace(name=renamed.get(bone.name, bone.name),
                           parent=renamed.get(bone.parent, bone.parent))
             for bone in _load("mixamo")]
    resolved = resolve_bones(bones, HEIGHT)
    assert resolved["hand_l"] == ("mixamorig:LeftWrist", "geometry")
    assert resolved["hand_r"] == ("mixamorig:RightWrist", "geometry")
    assert resolved["head"] == ("mixamorig:Skull", "geometry")
    # The forearm is still found by name.
    assert resolved["forearm_l"] == ("mixamorig:LeftForeArm", "name")


def test_geometric_fallback_on_unnamed_rig():
    original = _load("mixamo")
    renamed = {bone.name: f"Bone.{index:03d}" for index, bone in enumerate(original)}
    bones = [bone._replace(name=renamed[bone.name], parent=renamed.get(bone.parent, ""))
             for bone in original]
    resolved = resolve_bones(bones, HEIGHT)
    back = {new: old for old, new in renamed.items()}
    got = {key: (back[name], how) for key, (name, how) in resolved.items()}
    assert got == {
        "hand_l": ("mixamorig:LeftHand", "geometry"),
        "hand_r": ("mixamorig:RightHand", "geometry"),
        "forearm_l": ("mixamorig:LeftForeArm", "geometry"),
        "forearm_r": ("mixamorig:RightForeArm", "geometry"),
        "head": ("mixamorig:Head", "geometry"),
        "chest": ("mixamorig:Spine2", "geometry"),
        "hips": ("mixamorig:Hips", "geometry"),
    }


def _descendants(bones, name):
    names, grew = {name}, True
    while grew:
        more = {bone.name for bone in bones if bone.parent in names} - names
        names |= more
        grew = bool(more)
    return names


@pytest.mark.parametrize(("hand_scale", "forearm_scale"), [(1.6, 1.0), (2.2, 1.0), (1.0, 0.35)])
def test_geometric_hand_survives_big_hands_and_short_forearms(hand_scale, forearm_scale):
    # A stylised hand 1.6-2.2x a realistic one (0.12-0.17H wrist to fingertip),
    # or a forearm shorter than 0.12H: the walk still stops at the wrist, where
    # the finger chains branch.
    bones = _load("mixamo")
    wrist = next(b for b in bones if b.name == "mixamorig:RightHand").head.copy()
    elbow = next(b for b in bones if b.name == "mixamorig:RightForeArm").head.copy()
    hand = _descendants(bones, "mixamorig:RightHand")
    new_elbow = wrist + (elbow - wrist) * forearm_scale

    def moved(point):
        if np.allclose(point, elbow):
            return new_elbow
        return point

    bones = [bone._replace(head=wrist + (bone.head - wrist) * hand_scale,
                           tail=wrist + (bone.tail - wrist) * hand_scale)
             if bone.name in hand else bone._replace(head=moved(bone.head), tail=moved(bone.tail))
             for bone in bones]
    renamed = {bone.name: f"Bone.{index:03d}" for index, bone in enumerate(bones)}
    generic = [bone._replace(name=renamed[bone.name], parent=renamed.get(bone.parent, ""))
               for bone in bones]
    resolved = resolve_bones(generic, HEIGHT)
    assert resolved["hand_r"] == (renamed["mixamorig:RightHand"], "geometry")
    assert resolved["forearm_r"] == (renamed["mixamorig:RightForeArm"], "geometry")


def test_palm_socket_clamped():
    height = 2.0
    stub = BoneInfo("hand_r", np.array([-0.5, 0.0, 1.0]), np.array([-0.5, 0.0, 0.999]), "", True)
    long = BoneInfo("hand_l", np.array([0.5, 0.0, 1.0]), np.array([0.5, 0.0, 0.0]), "", True)
    mid = BoneInfo("lowerarm_l", np.array([0.3, 0.0, 1.2]), np.array([0.5, 0.0, 1.0]), "", True)
    resolved = {"hand_r": ("hand_r", "name"), "hand_l": ("hand_l", "name"),
                "forearm_l": ("lowerarm_l", "name")}
    sockets = bone_sockets(resolved, [stub, long, mid], height)
    # Stub: 0.5 * 0.04H = 0.04 m down the bone; long: 0.5 * 0.09H = 0.09 m.
    assert np.allclose(sockets["hand_r"], [-0.5, 0.0, 0.96])
    assert np.allclose(sockets["hand_l"], [0.5, 0.0, 0.91])
    assert np.allclose(sockets["forearm_l"], [0.4, 0.0, 1.1])
    # The fixture's 5.7 cm Mixamo hand is shorter than 0.04H (7.4 cm): the palm
    # sits 3.7 cm down the bone's 45-degree slope, (0.026, 0, -0.026) off its head.
    bones = _load("mixamo")
    palm = bone_sockets(resolve_bones(bones, HEIGHT), bones, HEIGHT)["hand_l"]
    assert np.allclose(palm, [0.55 + 0.026163, -0.02, 1.06 - 0.026163], atol=1e-5)


def test_facing_yaw_zero_for_minus_y_and_detects_90():
    front = {"hand_r": np.array([-0.5, 0.0, 1.0]), "hand_l": np.array([0.5, 0.0, 1.0])}
    assert facing_yaw(front) == 0.0
    turned = {"hand_r": np.array([0.0, -0.5, 1.0]), "hand_l": np.array([0.0, 0.5, 1.0])}
    assert facing_yaw(turned) == pytest.approx(90.0)
    # An A-pose ten degrees off square is still read as facing -Y.
    skew = {"hand_r": np.array([-0.5, -0.088, 1.0]), "hand_l": np.array([0.5, 0.088, 1.0])}
    assert facing_yaw(skew) == 0.0
    assert facing_yaw({"hand_r": np.zeros(3)}) == 0.0
