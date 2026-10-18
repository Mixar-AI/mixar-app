# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Roles belong to assemblies, not parts (the "cycle sf" bug: only one bike
tube moved, a pickup SIGN was the collectible and the tokens stayed static).

A synthetic hierarchy mirrors that scene; the real ``cycle_sf`` GLB from the
fork's fixtures (when the fork checkout is present) is replayed too."""

import json
import struct
from pathlib import Path

import pytest

from mixar.modules.game_studio.constants import ROLE_PROP
from mixar.modules.game_studio.core import agent_api, auto_roles, roles, spec
from mixar.modules.game_studio.core.assemblies import Hierarchy

FIXTURE = Path.home() / "Work/Mixar/mixar-godot/modules/mixar/tests/fixtures/cycle_sf/scene.glb"


@pytest.fixture
def cycle_scene(make_obj, make_scene):
    """WorkspaceRoot_* → SF_* groups → assets → parts, like the agent built."""
    objs = []

    def add(name, kind="MESH", parent=None, dims=(1, 1, 1)):
        obj = make_obj(name, kind, dimensions=dims, parent=parent)
        objs.append(obj)
        return obj

    bike_ws = add("WorkspaceRoot_7a35", "EMPTY")
    bike = add("SF_HeroBike", "EMPTY", bike_ws)
    for part in ("ChainStay-1", "ChainStay-2", "DownTube", "Saddle", "Fork", "Handlebar", "Chainring"):
        add(f"hero_bicycle_{part}", parent=bike)
    wheel = add("hero_bicycle_FrontWheel", "EMPTY", bike)  # a sub-group stays inside the bike
    for part in ("Rim", "Tire", "Hub"):
        add(f"hero_bicycle_FrontWheel{part}", parent=wheel)
    game_ws = add("WorkspaceRoot_96d5", "EMPTY")
    gameplay = add("SF_Gameplay", "EMPTY", game_ws)
    for i in range(12):
        token = add(f"gameplay_elements_Token{i:02d}", "EMPTY", gameplay)
        for part in ("Disk", "Rim", "Bolt"):
            add(f"gameplay_elements_Token{i:02d}{part}", parent=token)
    pickup = add("gameplay_elements_DeliveryPickup", "EMPTY", gameplay)
    for part in ("PickupBoard", "PickupFace", "PickupPlinth", "PickupSignPole"):
        add(f"gameplay_elements_{part}", parent=pickup)
    mailbox = add("gameplay_elements_MailboxDropoff", "EMPTY", gameplay)
    for part in ("MailboxBody", "MailboxFlag", "MailboxFlagStem", "MailboxPost"):
        add(f"gameplay_elements_{part}", parent=mailbox)
    start = add("gameplay_elements_RaceStart", "EMPTY", gameplay)
    for part in ("StartLine", "StartArch"):
        add(f"gameplay_elements_{part}", parent=start)
    cable = add("gameplay_elements_CableCar", "EMPTY", gameplay)
    for i in range(6):
        add(f"gameplay_elements_CarBench{i}", parent=cable)
    street_ws = add("WorkspaceRoot_132b", "EMPTY")
    street = add("SF_Street", "EMPTY", street_ws)
    add("street_ground_Road", parent=street, dims=(60, 12, 0.1))
    add("street_ground_SidewalkEast", parent=street)
    return make_scene(objs)


def test_assembly_roots_skip_containers(cycle_scene):
    hierarchy = Hierarchy(cycle_scene.objects)
    find = cycle_scene.objects.get
    assert hierarchy.assembly_root(find("hero_bicycle_ChainStay-1")).name == "SF_HeroBike"
    assert hierarchy.assembly_root(find("hero_bicycle_FrontWheelRim")).name == "SF_HeroBike"
    assert hierarchy.assembly_root(find("gameplay_elements_Token07Bolt")).name == "gameplay_elements_Token07"
    assert hierarchy.is_container(find("SF_Gameplay")) and hierarchy.is_container(find("WorkspaceRoot_7a35"))
    assert not hierarchy.is_container(find("SF_HeroBike"))
    assert hierarchy.assembly_root(find("SF_Gameplay")).name == "SF_Gameplay"  # a container is its own
    assert len(hierarchy.parts(find("SF_HeroBike"))) == 10


def _auto(scene, monkeypatch, overwrite=False):
    monkeypatch.setattr(agent_api, "_scene", lambda: scene)
    return agent_api.auto_assign_roles(apply=True, overwrite=overwrite)


def test_auto_assign_tags_assembly_roots(cycle_scene, monkeypatch):
    _auto(cycle_scene, monkeypatch)
    tagged = {o.name: roles.get_role(o) for o in cycle_scene.objects if roles.get_role(o)}
    assert tagged.pop("SF_HeroBike") == "player"
    tokens = {name for name, role in tagged.items() if role == "collectible"}
    assert tokens == {f"gameplay_elements_Token{i:02d}" for i in range(12)}
    assert tagged["gameplay_elements_MailboxDropoff"] == "goal"
    assert tagged["gameplay_elements_RaceStart"] == "spawn"
    assert "gameplay_elements_DeliveryPickup" not in tagged  # a sign, not a collectible
    assert "gameplay_elements_CableCar" not in tagged  # exactly one player
    assert not any(n.startswith("hero_bicycle_") or "Bolt" in n for n in tagged)  # no part tags
    find = cycle_scene.objects.get
    assert roles.effective_role(find("hero_bicycle_ChainStay-2")) == "player"
    assert roles.effective_role(find("hero_bicycle_FrontWheelHub")) == "player"
    assert roles.effective_role(find("gameplay_elements_Token03Rim")) == "collectible"


def test_spec_lists_role_roots_with_subtree(cycle_scene, monkeypatch):
    _auto(cycle_scene, monkeypatch)
    objects = [o for o in cycle_scene.objects if roles.in_game(o)]
    nodes = spec.build_nodes(objects)
    by_name = {n["name"]: n for n in nodes}
    assert by_name["SF_HeroBike"] == {"name": "SF_HeroBike", "role": "player", "params": {}, "subtree": True}
    assert not any(n.startswith("hero_bicycle_") or n.startswith("gameplay_elements_Token00") and n != "gameplay_elements_Token00"
                   for n in by_name)  # parts are covered by their root
    assert sum(1 for n in nodes if n["role"] == "collectible") == 12
    assert by_name["street_ground_Road"]["role"] == "static" and "subtree" not in by_name["street_ground_Road"]
    built = spec.build_spec(spec.DEFAULT_SETTINGS, nodes)
    assert spec.validate_spec(built)[0] == []
    summary = roles.role_summary(objects)
    assert summary["players"] == 1 and summary["counts"]["collectible"] == 12


def test_ui_and_agent_roles_go_to_the_assembly(cycle_scene, monkeypatch):
    monkeypatch.setattr(agent_api, "_scene", lambda: cycle_scene)
    find = cycle_scene.objects.get
    find("hero_bicycle_ChainStay-1")[ROLE_PROP] = "player"  # the old part-level tag
    reply = agent_api.set_game_roles([{"object": "hero_bicycle_Saddle", "role": "player"}])
    assert reply["applied"][0]["applied_to"] == "SF_HeroBike"
    assert roles.get_role(find("hero_bicycle_ChainStay-1")) is None  # one role per asset
    reply = agent_api.set_game_roles([{"object": "gameplay_elements_Token00Bolt", "role": "hazard",
                                       "part_only": True}])
    assert reply["applied"][0]["applied_to"] == "gameplay_elements_Token00Bolt"
    assert roles.effective_role(find("gameplay_elements_Token00Bolt")) == "hazard"


def test_overwrite_repairs_old_part_tags(cycle_scene, monkeypatch):
    find = cycle_scene.objects.get
    find("hero_bicycle_ChainStay-1")[ROLE_PROP] = "player"
    for part in ("PickupBoard", "PickupFace"):
        find(f"gameplay_elements_{part}")[ROLE_PROP] = "collectible"
    kept = _auto(cycle_scene, monkeypatch)
    assert roles.get_role(find("SF_HeroBike")) is None  # an explicit (part) tag is respected
    assert any(a["object"].startswith("gameplay_elements_Token") for a in kept["assignments"])
    _auto(cycle_scene, monkeypatch, overwrite=True)
    assert roles.get_role(find("SF_HeroBike")) == "player"
    assert roles.get_role(find("hero_bicycle_ChainStay-1")) is None
    assert roles.get_role(find("gameplay_elements_PickupBoard")) is None


def test_finish_beats_a_mailbox_flag(make_obj, make_scene):
    ws = make_obj("WorkspaceRoot_1", "EMPTY")
    group = make_obj("SF_Track", "EMPTY", parent=ws)
    objs = [ws, group]
    for root_name, parts in (("FinishLine", ("Banner", "Arch")), ("MailboxDropoff", ("MailboxFlag", "Body")),
                             ("Rock", ("A", "B"))):
        root = make_obj(root_name, "EMPTY", parent=group)
        objs += [root] + [make_obj(f"{root_name}{p}", parent=root) for p in parts]
    goals = [s for s in auto_roles.suggest_roles(objs) if s["role"] == "goal"]
    assert [g["object"] for g in goals] == ["FinishLine"]


def _glb_objects(make_obj, path):
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + length])
    nodes = gltf["nodes"]
    objs = [make_obj(n["name"], "MESH" if "mesh" in n else "EMPTY") for n in nodes]
    for index, node in enumerate(nodes):
        for child in node.get("children", ()):
            objs[child].parent = objs[index]
    return objs


@pytest.mark.skipif(not FIXTURE.is_file(), reason="needs the mixar-godot checkout's cycle_sf fixture")
def test_real_cycle_sf_scene(make_obj, make_scene, monkeypatch):
    scene = make_scene(_glb_objects(make_obj, FIXTURE))
    _auto(scene, monkeypatch)
    tagged = {o.name: roles.get_role(o) for o in scene.objects if roles.get_role(o)}
    players = [n for n, r in tagged.items() if r == "player"]
    collectibles = sorted(n for n, r in tagged.items() if r == "collectible")
    assert players == ["SF_HeroBike"]
    assert collectibles == [f"gameplay_elements_Token{i:02d}" for i in range(12)]
    assert [n for n, r in tagged.items() if r == "goal"] == ["gameplay_elements_MailboxDropoff"]
    assert [n for n, r in tagged.items() if r == "spawn"] == ["gameplay_elements_RaceStart"]
    objects = [o for o in scene.objects if roles.in_game(o)]
    nodes = spec.build_nodes(objects)
    assert spec.validate_spec(spec.build_spec(spec.DEFAULT_SETTINGS, nodes))[0] == []
    # Every bike part moves with the player.
    bike_parts = [o for o in scene.objects if o.name.startswith("hero_bicycle_")]
    assert bike_parts and all(roles.effective_role(o) == "player" for o in bike_parts)
