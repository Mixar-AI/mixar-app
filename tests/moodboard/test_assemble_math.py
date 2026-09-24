# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Assemble placement math: the DESIGN §2.3 rest rotations, pinned by hand.

Frames: character front -Y, up +Z, the character's left +X. A normalised part
has its long axis +Z (grip end at the bottom), the camera-facing side -Y and
image-right +X. Every expected vector below is worked out by hand from
Rx/Ry/Rz with column vectors, R_final = Rz(yaw) @ R_slot.
"""

import itertools
import math

import numpy as np
import pytest

from mixar.modules.moodboard.core.assemble_landmarks import (
    crossings,
    estimate_landmarks,
    head_width,
    outer_surface,
    ray_start,
    surface_query,
)
from mixar.modules.moodboard.core.assemble_math import (
    bone_key,
    normalize_part,
    plan_part,
    resolve_settings,
    rest_rotation,
    rot_z,
    sorted_extents,
    transform_points,
)

UP, TIP = np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0])
IMAGE_RIGHT = np.array([1.0, 0.0, 0.0])
CAMERA_FACE = np.array([0.0, -1.0, 0.0])
S25, C25 = math.sin(math.radians(25)), math.cos(math.radians(25))
S40, C40 = math.sin(math.radians(40)), math.cos(math.radians(40))


def _box(lo, hi):
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def _sword(upside_down=False):
    """1 m sword: round 20 cm grip, wide guard, flat blade -- grip at the bottom."""
    verts = (_box((-0.015, -0.015, 0.0), (0.015, 0.015, 0.2))
             + _box((-0.08, -0.012, 0.2), (0.08, 0.012, 0.22))
             + _box((-0.025, -0.003, 0.22), (0.025, 0.003, 1.0)))
    verts = np.array(verts, dtype=float)
    if upside_down:
        verts[:, 2] = 1.0 - verts[:, 2]
    return verts


def _body(palm_z=0.95, height=1.8, head_w=0.2, yaw=0.0):
    sockets = {
        "hand_r": np.array([-0.6, 0.0, palm_z]), "hand_l": np.array([0.6, 0.0, palm_z]),
        "forearm_r": np.array([-0.45, 0.0, 1.1]), "forearm_l": np.array([0.45, 0.0, 1.1]),
        "chest": np.array([0.0, 0.0, 1.3]), "hips": np.array([0.0, 0.0, 0.9]),
        "head": np.array([0.0, 0.0, 1.58]),
    }
    return {"height": height, "zmin": 0.0, "top": height, "yaw": yaw,
            "head_width": head_w, "sockets": sockets}


def _settings(label, verts, **rows):
    return resolve_settings(label, sorted_extents(verts), **rows)


def test_point_maps_tip_forward_edge_down_face_left():
    for slot in ("HAND_R", "HAND_L"):
        rot = rest_rotation(slot, 'POINT', True, False, 0.0)
        assert np.allclose(rot @ TIP, [0, -1, 0])          # tip forward
        assert np.allclose(rot @ IMAGE_RIGHT, [0, 0, 1])   # image-left edge points down
        assert np.allclose(rot @ CAMERA_FACE, [1, 0, 0])   # camera face toward +X


def test_upright_string_toward_body_both_hands():
    right = rest_rotation('HAND_R', 'UPRIGHT', True, False, 0.0)
    left = rest_rotation('HAND_L', 'UPRIGHT', True, False, 0.0)
    # The right hand is at -X, the left at +X: the string (image-right) faces the body.
    assert np.allclose(right @ IMAGE_RIGHT, [1, 0, 0])
    assert np.allclose(left @ IMAGE_RIGHT, [-1, 0, 0])
    assert np.allclose(right @ UP, [0, 0, 1]) and np.allclose(left @ UP, [0, 0, 1])


def test_face_out_normals_point_outward():
    for slot, outward in (('HAND_L', [1, 0, 0]), ('FOREARM_L', [1, 0, 0]),
                          ('HAND_R', [-1, 0, 0]), ('FOREARM_R', [-1, 0, 0])):
        rot = rest_rotation(slot, 'FACE_OUT', False, False, 0.0)
        assert np.allclose(rot @ CAMERA_FACE, outward), slot
        assert np.allclose(rot @ UP, [0, 0, 1]), slot


def test_back_quiver_faces_back_top_toward_right_shoulder():
    rot = rest_rotation('BACK', '', True, False, 0.0)
    assert np.allclose(rot @ CAMERA_FACE, [0, 1, 0])
    assert np.allclose(rot @ UP, [-S25, 0, C25])  # leans toward the right shoulder (-X)
    compact = rest_rotation('BACK', '', False, False, 0.0)
    assert np.allclose(compact @ CAMERA_FACE, [0, 1, 0])
    assert np.allclose(compact @ UP, [0, 0, 1])
    # Placement: the quiver's inner face sits 0.004H behind the hit on the back.
    verts = np.array(_box((-0.06, -0.06, 0.0), (0.06, 0.06, 0.8)))
    settings = _settings("Quiver", verts)
    assert (settings.slot, settings.hold, settings.size_pct) == ('BACK', '', 45.0)
    body = _body()
    hit = np.array([0.0, 0.15, 1.25])
    placed = transform_points(plan_part(verts, settings, body, hit).delta, verts)
    assert placed[:, 1].min() == pytest.approx(0.15 + 0.004 * 1.8)
    assert np.allclose((placed.min(0) + placed.max(0))[[0, 2]] / 2, [0.0, 1.25])


def test_hip_sheath_hilt_forward_up():
    left = rest_rotation('HIP_L', '', True, False, 0.0)
    right = rest_rotation('HIP_R', '', True, False, 0.0)
    for rot in (left, right):
        assert np.allclose(rot @ UP, [0, -S40, C40])  # the top points forward and up
    assert np.allclose(left @ CAMERA_FACE, [1, 0, 0])
    assert np.allclose(right @ CAMERA_FACE, [-1, 0, 0])
    assert np.allclose(rest_rotation('HIP_L', '', False, False, 0.0) @ CAMERA_FACE, [1, 0, 0])


def test_flip_mirrors_edge():
    plain = rest_rotation('HAND_R', 'POINT', True, False, 0.0)
    flipped = rest_rotation('HAND_R', 'POINT', True, True, 0.0)
    assert np.allclose(plain @ IMAGE_RIGHT, [0, 0, 1])
    assert np.allclose(flipped @ IMAGE_RIGHT, [0, 0, -1])
    assert np.allclose(flipped @ TIP, [0, -1, 0])
    assert np.allclose(flipped @ CAMERA_FACE, [-1, 0, 0])


def test_yaw_applies_to_every_slot():
    slots = ('HAND_R', 'HAND_L', 'FOREARM_R', 'FOREARM_L', 'BACK', 'HIP_R', 'HIP_L',
             'HEAD_FRONT', 'HEAD_TOP', 'FLOAT_R', 'FLOAT_L')
    holds = ('POINT', 'UPRIGHT', 'FACE_OUT', 'AS_IS', '')
    for slot, hold, is_long, flip in itertools.product(slots, holds, (True, False), (True, False)):
        base = rest_rotation(slot, hold, is_long, flip, 0.0)
        turned = rest_rotation(slot, hold, is_long, flip, 90.0)
        assert np.allclose(turned, rot_z(90) @ base), (slot, hold)
    # Turned 90 degrees, the character faces +X: a pointed blade points +X.
    assert np.allclose(rest_rotation('HAND_R', 'POINT', True, False, 90.0) @ TIP, [1, 0, 0])


def test_grip_end_detection_flips_upside_down_sword():
    upright = _sword()
    settings = _settings("Sword", upright)
    matrix, notes = normalize_part(upright, settings)
    assert np.allclose(matrix, np.eye(4)) and notes == []

    flipped = _sword(upside_down=True)
    matrix, notes = normalize_part(flipped, settings)
    assert notes == ["orientation inferred"]
    fixed = transform_points(matrix, flipped)
    grip = fixed[np.abs(fixed[:, 0]) <= 0.015]
    assert grip[:, 2].min() == pytest.approx(fixed[:, 2].min())
    assert grip[:, 2].max() == pytest.approx(fixed[:, 2].min() + 0.2)
    # A thin blade tip is a smaller slab than the hilt: an upright sword is
    # still never flipped on area alone.
    tip_heavy = np.vstack([upright, [[0.0, 0.0, 1.05]]])
    assert np.allclose(normalize_part(tip_heavy, settings)[0], np.eye(4))


def test_longest_axis_inferred_for_lying_part():
    # A staff lying along +Y, its big ornament at the +Y end.
    verts = np.array(_box((-0.015, 0.0, -0.015), (0.015, 1.0, 0.015))
                     + _box((-0.06, 0.9, -0.06), (0.06, 1.0, 0.06)))
    settings = _settings("Staff", verts)
    matrix, notes = normalize_part(verts, settings)
    assert notes == ["orientation inferred"]
    fixed = transform_points(matrix, verts)
    extent = np.ptp(fixed, axis=0)
    assert extent[2] == pytest.approx(1.0) and extent[0] == pytest.approx(0.12)
    # Rx(+90): +Y becomes +Z, so the ornament ends on top and the grip end below.
    ornament = fixed[np.abs(fixed[:, 0]) > 0.02]
    assert ornament[:, 2].min() == pytest.approx(fixed[:, 2].max() - 0.1)
    # Compact and AS_IS parts are never re-oriented.
    lantern = _settings("Lantern", verts)
    assert np.allclose(normalize_part(verts, lantern)[0], np.eye(4))


def test_absolute_scale_is_idempotent():
    verts = _sword() * 3.0 + np.array([5.0, -2.0, 7.0])  # wherever the import landed
    settings = _settings("Talwar", verts)
    body = _body()
    first = plan_part(verts, settings, body)
    second = plan_part(verts.copy(), settings, body)
    assert np.array_equal(first.delta, second.delta)
    assert first.size_m == pytest.approx(0.52 * 1.8)
    placed = transform_points(first.delta, verts)
    assert np.ptp(placed, axis=0).max() == pytest.approx(0.936)
    # The grip (10% up from the pommel, on the centre line) lands on the palm,
    # and the blade points forward (-Y) from it.
    pommel = transform_points(first.delta, [[5.0, -2.0, 7.0]])[0]
    assert np.allclose(pommel, [-0.6, 0.0936, 0.95])
    assert placed[:, 1].min() == pytest.approx(0.0936 - 0.936)


def test_pole_grounded_when_reachable():
    pole = np.array(_box((-0.02, -0.02, 0.0), (0.02, 0.02, 2.0)))
    spear = _settings("Spear", pole)
    assert (spear.slot, spear.hold, spear.size_pct, spear.grip) == ('HAND_R', 'UPRIGHT', 120.0, 0.4)
    # 2.16 m spear held 0.864 m up: from a 0.8 m palm it would sink 6.4 cm.
    low = plan_part(pole, spear, _body(palm_z=0.8))
    assert "planted on the ground" in low.notes
    assert transform_points(low.delta, pole)[:, 2].min() == pytest.approx(0.0)
    high = plan_part(pole, spear, _body(palm_z=1.2))
    assert "planted on the ground" not in high.notes
    assert transform_points(high.delta, pole)[:, 2].min() == pytest.approx(1.2 - 0.864)
    # Below 80% a pole is never planted, even when it reaches under the floor.
    short = _settings("Spear", pole, size_pct=60.0)
    placed = transform_points(plan_part(pole, short, _body(palm_z=0.2)).delta, pole)
    assert placed[:, 2].min() == pytest.approx(0.2 - 0.4 * 1.08)


def test_head_slots_size_by_head_width():
    goggles = np.array(_box((-0.1, -0.03, 0.0), (0.1, 0.03, 0.05)))
    settings = _settings("Goggles", goggles)
    assert (settings.slot, settings.basis, settings.size_pct) == ('HEAD_FRONT', 'head', 95.0)
    body = _body(head_w=0.2)
    plan = plan_part(goggles, settings, body, hit=np.array([0.0, -0.1, 1.7]))
    placed = transform_points(plan.delta, goggles)
    assert np.ptp(placed, axis=0).max() == pytest.approx(0.19)
    assert placed[:, 1].max() == pytest.approx(-0.1 - 0.004 * 1.8)
    crown = np.array(_box((-0.05, -0.05, 0.0), (0.05, 0.05, 0.04)))
    settings = _settings("Crown", crown, size_pct=50.0)
    plan = plan_part(crown, settings, body, hit=np.array([0.0, 0.0, 1.8]))
    placed = transform_points(plan.delta, crown)
    assert np.ptp(placed, axis=0).max() == pytest.approx(0.1)
    # The crown sinks 10% of its own height into the head.
    assert placed[:, 2].min() == pytest.approx(1.8 - 0.1 * 0.04)
    # A head keyword's size is not reused when the part is moved to a hand.
    moved = _settings("Goggles", goggles, slot='HAND_L')
    assert (moved.basis, moved.hold, moved.size_pct) == ('height', 'AS_IS', 17.0)


def test_static_landmarks_on_synthetic_a_pose_cloud():
    cloud = np.array(
        [(0.1, 0.0, 0.0), (-0.1, 0.0, 0.0)]
        + _box((-0.15, -0.1, 0.9), (0.15, 0.1, 1.5))
        + _box((-0.1, -0.1, 1.55), (0.1, 0.1, 1.8))
        + [(0.09, 0.0, 1.68), (-0.09, 0.0, 1.68), (0.0, 0.1, 1.68), (0.0, -0.1, 1.68)]
        + _box((0.58, -0.02, 0.93), (0.62, 0.02, 0.97))
        + _box((-0.62, -0.02, 0.93), (-0.58, 0.02, 0.97)))
    marks = estimate_landmarks(cloud)
    assert np.allclose(marks["hand_l"], [0.6, 0.0, 0.95])
    assert np.allclose(marks["hand_r"], [-0.6, 0.0, 0.95])
    assert np.allclose(marks["chest"], [0.0, 0.0, 0.72 * 1.8])
    assert np.allclose(marks["hips"], [0.0, 0.0, 0.9])
    assert np.allclose(marks["head"], [0.0, 0.0, 1.8 - 0.12 * 1.8])
    # 0.216 m from the hand toward the chest: unit (-0.6, 0, 0.346) / 0.6926.
    assert np.allclose(marks["forearm_l"], [0.4129, 0.0, 1.0579], atol=1e-4)
    # Eye level 1.584 + 0.45 * 0.216 = 1.6812: the ring there is 0.18 wide in x, 0.2 in y.
    assert head_width(cloud, marks["head"], 1.8, 1.8, 0.0) == pytest.approx(0.18)
    assert head_width(cloud, marks["head"], 1.8, 1.8, 90.0) == pytest.approx(0.2)
    back_anchor, back_out = surface_query("BACK", marks, 1.8, 1.8, 0.0)
    assert np.allclose(back_anchor, [0.0, 0.0, 1.296 - 0.054]) and np.allclose(back_out, [0, 1, 0])
    front_anchor, front_out = surface_query("HEAD_FRONT", marks, 1.8, 1.8, 0.0)
    assert np.allclose(front_anchor, [0.0, 0.0, 1.6812 + 0.0216])
    assert np.allclose(front_out, [0, -1, 0])
    assert np.allclose(surface_query("HIP_R", marks, 1.8, 1.8, 0.0)[1], [-1, 0, 0])
    assert np.allclose(surface_query("HEAD_TOP", marks, 1.8, 1.8, 0.0)[0], [0.0, 0.0, 1.8])
    assert surface_query("HAND_R", marks, 1.8, 1.8, 0.0) is None
    assert surface_query("FLOAT_L", marks, 1.8, 1.8, 0.0) is None


def test_auto_settings_resolution_order():
    blade = np.array(_box((-0.02, -0.005, 0.0), (0.02, 0.005, 1.0)))
    # The template's generic labels carry only side words.
    right = _settings("Right-hand item", blade)
    assert (right.slot, right.hold, right.size_pct, right.grip) == ('HAND_R', 'POINT', 50.0, 0.12)
    assert right.slot_guessed and right.hold_guessed
    left = _settings("Left-hand item", blade)
    assert (left.slot, left.hold, left.size_pct, left.grip) == ('HAND_L', 'UPRIGHT', 90.0, 0.4)
    # An explicit row beats every word; an explicit size >= 80 stands a blade up.
    explicit = _settings("Right-hand item", blade, slot='HAND_L', hold='POINT', size_pct=30.0)
    assert (explicit.slot, explicit.hold, explicit.size_pct) == ('HAND_L', 'POINT', 30.0)
    assert not explicit.slot_guessed and not explicit.hold_guessed
    assert _settings("Mystery pole", blade, size_pct=90.0).hold == 'UPRIGHT'
    assert _settings("left sword", blade).slot == 'HAND_L'
    assert _settings("Left-handed sword", blade).slot == 'HAND_L'
    assert _settings("Left-handed scabbard", blade).slot == 'HIP_R'
    assert _settings("Turban jewel", blade).warnings == ["'turban' usually stays on the body mesh"]
    shield = np.array(_box((-0.3, -0.03, 0.0), (0.3, 0.03, 0.6)))
    assert (_settings("Round thing", shield).slot, _settings("Round thing", shield).hold) == (
        'HAND_L', 'FACE_OUT')
    assert _settings("Round thing", shield, slot='FOREARM_L').size_pct == 45.0
    assert _settings("Quiver", blade).hold == ''
    assert [bone_key(s) for s in ('HAND_R', 'FLOAT_L', 'FOREARM_R', 'BACK', 'HIP_L',
                                  'HEAD_TOP')] == [
        'hand_r', 'hand_l', 'forearm_r', 'chest', 'hips', 'head']


def test_flip_only_turns_hand_items():
    # "Flip edge" is drawn for hand slots only: a stale hidden row must not
    # turn goggles into the head or a forearm shield inward.
    shield = _box((-0.3, -0.03, 0.0), (0.3, 0.03, 0.6))
    assert _settings("Talwar", _sword(), slot='HAND_L', flip=True).flip
    for label, slot in (("Goggles", 'HEAD_FRONT'), ("Dhal", 'FOREARM_L'), ("Quiver", 'BACK')):
        settings = _settings(label, shield, slot=slot, flip=True)
        assert not settings.flip, slot
    goggles = _settings("Goggles", shield, slot='HEAD_FRONT', flip=True)
    rot = rest_rotation(goggles.slot, goggles.hold, False, goggles.flip, 0.0)
    assert np.allclose(rot @ CAMERA_FACE, CAMERA_FACE)


def test_surface_ray_starts_inside_and_skips_past_a_gap():
    height = 1.8
    # Pelvis exit at 0.15, a belt 2 cm out, then an A-pose hand 0.38 m further.
    assert outer_surface([0.64, 0.15, 0.53, 0.17], height) == pytest.approx(0.17)
    assert outer_surface([], height) is None
    sockets = {"head": np.array([0.0, 0.01, 1.58])}
    anchor, up = surface_query("HEAD_TOP", sockets, 1.8, height, 0.0)
    assert np.allclose(ray_start("HEAD_TOP", sockets, anchor), [0.0, 0.01, 1.58])
    assert np.allclose(ray_start("BACK", sockets, anchor), anchor)
    # Walking successive crossings of a 0.1-0.3 box and a 0.5-0.6 box from x = 0.
    walls = [0.1, 0.3, 0.5, 0.6]

    def cast(origin):
        ahead = [w for w in walls if w > origin[0]]
        return None if not ahead else np.array([ahead[0], 0.0, 0.0])

    hits = crossings(cast, np.zeros(3), np.array([1.0, 0.0, 0.0]), height)
    assert hits == pytest.approx(walls)
    assert crossings(cast, np.zeros(3), np.array([1.0, 0.0, 0.0]), 0.4) == pytest.approx([0.1, 0.3])
