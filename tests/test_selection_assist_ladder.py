# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the selection-assist grouping keys and suggestion ladder.

Pure logic only (core/keys.py, core/ladder.py) — no bpy. The synthetic
scene mirrors the real kitchen test scene: two bar stools whose 8 legs are
geometrically identical but have distinct mesh datablocks, plus a fridge
whose two doors differ geometrically and only group by name stem.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.selection_assist.core.keys import (  # noqa: E402
    geometry_signature,
    name_stem,
    pretty_label,
)
from mixar.modules.selection_assist.core.ladder import (  # noqa: E402
    ObjectRecord,
    SceneSnapshotIndex,
    build_ladder,
)

LEG_SIG = geometry_signature("MESH", (0.0312, 0.0321, 0.7206), (28, 54, 26))
SEAT_SIG = geometry_signature("MESH", (0.4, 0.4, 0.05), (220, 440, 222))


def _stool(prefix, root):
    metal = ("Charcoal Powder Coat",)
    records = [ObjectRecord(root, "EMPTY", root, geometry_signature("EMPTY", ()), name_stem(root), ())]
    for corner in ("Front_Left", "Front_Right", "Rear_Left", "Rear_Right"):
        name = "{}_Leg_{}".format(prefix, corner)
        records.append(
            ObjectRecord(name, "MESH", root, LEG_SIG, name_stem(name), metal)
        )
    seat = "{}_Molded_Seat".format(prefix)
    records.append(
        ObjectRecord(seat, "MESH", root, SEAT_SIG, name_stem(seat), ("Oak Veneer",))
    )
    # Footrest shares the legs' material but not their geometry/stem — keeps
    # the material level distinct from the same-part levels.
    rest = "{}_Footrest".format(prefix)
    records.append(
        ObjectRecord(rest, "MESH", root,
                     geometry_signature("MESH", (0.35, 0.02, 0.02), (16, 28, 14)),
                     name_stem(rest), metal)
    )
    return records


def _kitchen_index():
    records = []
    records += _stool("Stool", "Modern_Bar_Stool_Root")
    # Second stool: Blender duplicate names, same geometry, own root.
    records += [
        ObjectRecord(
            r.name + ".001", r.obj_type, "Modern_Bar_Stool_Root.001",
            r.signature, r.stem, r.materials,
        )
        for r in _stool("Stool", "Modern_Bar_Stool_Root")
    ]
    # Fridge: two doors, different geometry, same stem.
    fridge_root = "Fridge_Root"
    records.append(ObjectRecord(fridge_root, "EMPTY", fridge_root,
                                geometry_signature("EMPTY", ()), name_stem(fridge_root), ()))
    for name, dims in (("Fridge_Door_Upper", (0.6, 0.05, 0.8)),
                       ("Fridge_Door_Lower", (0.6, 0.05, 1.0))):
        records.append(
            ObjectRecord(name, "MESH", fridge_root,
                         geometry_signature("MESH", dims, (300, 600, 302)),
                         name_stem(name), ("Brushed Steel",))
        )
    return SceneSnapshotIndex(records)


# -- keys ---------------------------------------------------------------------

def test_name_stem_strips_direction_and_suffix():
    assert name_stem("Stool_Leg_Front_Left.001") == "stool leg"
    assert name_stem("Stool_Leg_Rear_Right") == "stool leg"
    assert name_stem("Fridge_Door_Upper") == "fridge door"


def test_name_stem_keeps_order_and_falls_back():
    assert name_stem("Left_Drawer_Stack_Drawer_1_Finger_Lip") == \
        "drawer stack drawer finger lip"
    # All tokens dropped -> falls back to the full token list.
    assert name_stem("Left_Right") == "left right"


def test_geometry_signature_rounds_float_noise():
    a = geometry_signature("MESH", (0.03121, 0.03209, 0.72058), (28, 54, 26))
    assert a == LEG_SIG


def test_pretty_label():
    assert pretty_label("Modern_Bar_Stool_Root.001") == "Modern Bar Stool"


# -- ladder ---------------------------------------------------------------------

def test_leg_ladder_levels():
    index = _kitchen_index()
    ladder = build_ladder(index, "Stool_Leg_Front_Left", {"Stool_Leg_Front_Left"})
    keys = [lv.key for lv in ladder]
    by_key = {lv.key: lv for lv in ladder}

    # 4 legs in this stool -> 8 legs scene-wide (signature groups them even
    # though each leg has its own datablock) -> whole stool -> both stools.
    assert keys[0] == "same_part_asset"
    assert len(by_key["same_part_asset"].names) == 4
    assert len(by_key["same_part_scene"].names) == 8
    assert len(by_key["asset"].names) == 7  # root + 4 legs + seat + footrest
    assert len(by_key["instances"].names) == 14
    # Material level: 8 legs + 2 footrests share Charcoal Powder Coat.
    assert len(by_key["material"].names) == 10
    # Narrow-to-broad ordering.
    sizes = [len(lv.names) for lv in ladder]
    assert sizes == sorted(sizes)


def test_every_level_contains_seed():
    index = _kitchen_index()
    seed = {"Stool_Leg_Front_Left", "Stool_Molded_Seat"}
    for level in build_ladder(index, "Stool_Leg_Front_Left", seed):
        assert seed <= set(level.names)


def test_fridge_doors_group_by_stem_despite_different_geometry():
    index = _kitchen_index()
    ladder = build_ladder(index, "Fridge_Door_Upper", {"Fridge_Door_Upper"})
    by_key = {lv.key: lv for lv in ladder}
    assert by_key["same_part_asset"].names == frozenset(
        {"Fridge_Door_Upper", "Fridge_Door_Lower"}
    )


def test_unique_object_gets_no_same_part_level():
    index = _kitchen_index()
    ladder = build_ladder(index, "Stool_Molded_Seat", {"Stool_Molded_Seat"})
    keys = {lv.key for lv in ladder}
    # Seat matches its scene-wide twin (other stool) but nothing in-asset.
    assert "same_part_asset" not in keys
    assert "same_part_scene" in keys


def test_empty_root_gets_no_same_part_levels():
    # Asset-root empties all share a degenerate signature; they must never
    # produce "matching parts" suggestions — only asset/instances levels.
    index = _kitchen_index()
    ladder = build_ladder(index, "Modern_Bar_Stool_Root", {"Modern_Bar_Stool_Root"})
    keys = {lv.key for lv in ladder}
    assert "same_part_asset" not in keys
    assert "same_part_scene" not in keys
    assert "asset" in keys
    assert "instances" in keys


def test_unknown_active_returns_empty_ladder():
    index = _kitchen_index()
    assert build_ladder(index, "Nope", {"Nope"}) == []


def test_oversized_levels_are_dropped():
    index = _kitchen_index()
    ladder = build_ladder(
        index, "Stool_Leg_Front_Left", {"Stool_Leg_Front_Left"}, max_level_objects=5
    )
    assert all(len(lv.names) <= 5 for lv in ladder)
    assert any(lv.key == "same_part_asset" for lv in ladder)
    assert not any(lv.key == "instances" for lv in ladder)
