# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animation edits must stay inside the owner's slot and process drivers once."""

import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from mixar.modules.common.utils import animation
from mixar.modules.paint.utils import common_animation as paint


@pytest.fixture
def slots(monkeypatch):
    module = ModuleType("bpy_extras.anim_utils")
    module.animdata_get_channelbag_for_assigned_slot = (
        lambda ad: ad.action.bags.get(ad.action_slot)
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    own = [NS(data_path='nodes["Value"].inputs[0].default_value'),
           NS(data_path="mp.layers[0].intensity_value")]
    foreign = [NS(data_path="mp.layers[0].intensity_value")]
    action = NS(bags={"own": NS(fcurves=own), "foreign": NS(fcurves=foreign)})
    tree = NS(animation_data=NS(action=action, action_slot="own", drivers=[]))
    return tree, own, foreign


def test_material_and_paint_reads_use_only_assigned_slot(slots):
    tree, own, foreign = slots
    assert paint.get_material_fcurves(NS(node_tree=tree)) == own[:1]
    assert paint.get_mp_fcurves(NS(id_data=tree)) == own
    assert animation.action_fcurves(tree) is own
    assert all(fc is not foreign[0] for fc in animation.assigned_fcurves(tree))


def test_removal_does_not_touch_other_slots(slots):
    tree, own, foreign = slots
    assert animation.remove_fcurves(tree, {"mp.layers[0].intensity_value"}) == 1
    assert len(own) == 1
    assert len(foreign) == 1


def test_driver_collection_is_visited_once(slots):
    tree, own, _ = slots
    drivers = [NS(data_path="driver_a"), NS(data_path="driver_b")]
    tree.animation_data.drivers = drivers
    collections = paint.get_action_and_driver_fcurves(tree)
    assert len(collections) == 2
    assert collections[0] is own
    assert collections[1] is drivers
    # Mimic a destructive modifier transfer; repeated collection visits would
    # reprocess or lose drivers as their paths are rewritten by the caller.
    visited = []
    for collection in collections:
        for curve in collection:
            visited.append(id(curve))
    assert len(visited) == len(set(visited))


def test_missing_slot_never_borrows_another_owners_animation(slots):
    tree, own, foreign = slots
    tree.animation_data.action_slot = None
    assert animation.assigned_fcurves(tree) == ()
    assert animation.remove_fcurves(tree, {foreign[0].data_path}) == 0
    assert len(own) == 2 and len(foreign) == 1


def test_empty_action_slot_returns_editable_collection(slots):
    tree, own, _ = slots
    own.clear()
    assert animation.action_fcurves(tree) is own


def test_no_action_still_exposes_drivers_once():
    drivers = [object(), object()]
    tree = NS(animation_data=NS(action=None, drivers=drivers))
    assert paint.get_action_and_driver_fcurves(tree) == [drivers]
    assert animation.assigned_fcurves(NS(animation_data=None)) == ()


def test_legacy_action_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy_extras.anim_utils", None)
    curves = [NS(data_path="location")]
    tree = NS(animation_data=NS(action=NS(fcurves=curves)))
    assert animation.action_fcurves(tree) is curves
    assert animation.remove_fcurves(tree, {"location"}) == 1
    assert curves == []
