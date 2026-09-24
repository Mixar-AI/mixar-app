# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Where Assemble and the Character Sheet to 3D workflow are offered."""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.ui import moodboard_menu_actions as actions

MOODBOARD = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/moodboard"


def _read(relative: str) -> str:
    return (MOODBOARD / relative).read_text(encoding="utf-8")


def _scene(actions_=(), assets=()):
    return NS(mixie_moodboard_action_nodes=list(actions_),
              mixie_moodboard_asset_nodes=list(assets), mixie_moodboard_links=[],
              mixie_moodboard_images=[])


@pytest.fixture
def catalog(monkeypatch):
    """Every mesh feature is live; Auto Rig's template availability is the knob."""
    state = {'auto_rig': True}
    monkeypatch.setattr(actions, "capability_available", lambda capability: True)
    monkeypatch.setattr(actions, "template_available",
                        lambda template: state['auto_rig'] if template == 'AUTO_RIG' else True)
    return state


def _ids(entries):
    return [entry[0] for entry in entries]


def test_a_rig_result_continues_into_assemble(catalog):
    scene = _scene([NS(node_id="rig", action_type='AUTO_RIG')])
    entries = actions.mesh_continuations_for(scene, "rig")
    assert _ids(entries) == ['PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG', 'ASSEMBLE']
    assert entries[-1] == actions.ASSEMBLE_CONTINUATION


def test_assemble_offers_no_continuation(catalog):
    scene = _scene([NS(node_id="asm", action_type='ASSEMBLE')])
    assert actions.mesh_continuations_for(scene, "asm") == []


def test_a_3d_result_offers_assemble_only_without_auto_rig(catalog):
    scene = _scene([NS(node_id="m3d", action_type='MODEL_3D')])
    assert 'ASSEMBLE' not in _ids(actions.mesh_continuations_for(scene, "m3d"))
    catalog['auto_rig'] = False
    assert 'ASSEMBLE' in _ids(actions.mesh_continuations_for(scene, "m3d"))


def test_other_mesh_features_do_not_offer_assemble(catalog):
    scene = _scene([NS(node_id="pbr", action_type='PBR_GEN')])
    assert 'ASSEMBLE' not in _ids(actions.mesh_continuations_for(scene, "pbr"))


def test_an_asset_offers_assemble_only_when_its_mesh_has_an_armature(catalog):
    rigged = NS(node_id="rigged", preview_object=NS(type='MESH', find_armature=lambda: object()))
    rig = NS(node_id="rig", preview_object=NS(type='ARMATURE', find_armature=lambda: None))
    plain = NS(node_id="plain", preview_object=NS(type='MESH', find_armature=lambda: None))
    legacy = NS(node_id="legacy", preview_object=None)
    scene = _scene(assets=[rigged, rig, plain, legacy])
    assert 'ASSEMBLE' in _ids(actions.mesh_continuations_for(scene, "rigged"))
    assert 'ASSEMBLE' in _ids(actions.mesh_continuations_for(scene, "rig"))
    assert 'ASSEMBLE' not in _ids(actions.mesh_continuations_for(scene, "plain"))
    assert 'ASSEMBLE' not in _ids(actions.mesh_continuations_for(scene, "legacy"))


def test_unavailable_mesh_features_are_filtered(catalog, monkeypatch):
    monkeypatch.setattr(actions, "capability_available", lambda capability: capability == "animate")
    scene = _scene([NS(node_id="rig", action_type='AUTO_RIG')])
    assert _ids(actions.mesh_continuations_for(scene, "rig")) == ['AUTO_RIG', 'ASSEMBLE']


class _Layout:
    def __init__(self):
        self.calls = []

    def operator(self, idname, **kwargs):
        op = NS()
        self.calls.append((idname, kwargs, op))
        return op


def test_character_sheet_entry_carries_its_source_and_drop():
    layout = _Layout()
    op = actions.draw_character_sheet_entry(layout, "sheet", (10.0, 20.0))
    idname, kwargs, _op = layout.calls[0]
    assert idname == "mixie.moodboard_add_template"
    assert kwargs == {"text": "Character Sheet to 3D", "icon": 'COMMUNITY'}
    assert (op.template, op.source_node_id) == ('CHARACTER_SHEET_3D', "sheet")
    assert (op.from_drop, op.drop_x, op.drop_y) == (True, 10.0, 20.0)

    click = actions.draw_character_sheet_entry(layout)
    assert click.source_node_id == "" and not hasattr(click, "from_drop")


def test_both_menus_route_through_the_shared_helpers():
    output_menu = _read("ui/moodboard_output_menu.py")
    context_menu = _read("ui/moodboard_menus.py")
    for menu in (output_menu, context_menu):
        assert "mesh_continuations_for(scene, " in menu
        assert "MESH_CONTINUATIONS" not in menu
        assert "template_available('CHARACTER_SHEET_3D')" in menu
    assert "draw_character_sheet_entry(layout, source_id, drop)" in output_menu
    assert "_draw_character_sheet_entry(layout, action_node.node_id)" in context_menu
    assert "_draw_character_sheet_entry(layout)" in context_menu
    # The IMAGE_GEN continuation sits inside that node's "Continue With" block.
    continue_with = context_menu.split("if action_node.action_type == 'IMAGE_GEN':")[1]
    continue_with = continue_with.split("if can_continue and")[0]
    assert "_draw_character_sheet_entry(layout, action_node.node_id)" in continue_with


def test_add_menus_keep_listing_every_available_template():
    node_menus = _read("ui/moodboard_node_menus.py")
    assert "for item in available_templates():" in node_menus
    assert "draw_template(layout, item, drop=drop)" in node_menus
