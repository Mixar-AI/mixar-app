# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Meshes a game GLB cannot show (``core/visuals.py``): volume-only and
fully transparent materials, and particle emitters shown only as their
particles, are left out of the game (not given an opaque box with
collision), and procedural base colours are reported as flat colour. Found
on Mixie's temple arena: eight volume haze cards and six smoke plumes became
grey walls."""

import types

import pytest

from mixar.modules.game_studio.constants import ROLE_PROP
from mixar.modules.game_studio.core import visuals


class Sockets(list):
    def get(self, name, default=None):
        return next((s for s in self if s.name == name), default)


def _socket(name, source=None, value=1.0):
    links = [types.SimpleNamespace(from_node=source)] if source is not None else []
    return types.SimpleNamespace(name=name, links=links, is_linked=bool(links), default_value=value)


def _node(type_, **inputs):
    return types.SimpleNamespace(type=type_, image=None, inputs=Sockets(
        _socket(n, *(v if isinstance(v, tuple) else (v,))) for n, v in inputs.items()))


def _material(name, surface=None, volume=None):
    output = types.SimpleNamespace(type="OUTPUT_MATERIAL", is_active_output=True,
                                   inputs=Sockets([_socket("Surface", surface), _socket("Volume", volume)]))
    nodes = [output] + [n for n in (surface, volume) if n is not None]
    return types.SimpleNamespace(name=name, node_tree=types.SimpleNamespace(nodes=nodes))


def _principled(alpha=1.0, base=None):
    return _node("BSDF_PRINCIPLED", **{"Alpha": (None, alpha), "Base Color": (base,)})


def _mesh(make_obj, name, *materials, particles=0, show_emitter=True):
    obj = make_obj(name, "MESH")
    obj.data = types.SimpleNamespace(materials=list(materials))
    obj.particle_systems = [object()] * particles
    obj.show_instancer_for_render = show_emitter
    return obj


HAZE = _material("arena_atmosphere_Cool_Haze", volume=_node("PRINCIPLED_VOLUME"))
STONE = _material("Stone", surface=_principled())


@pytest.mark.parametrize("material,kind", [
    (HAZE, "volume"),
    (_material("Glass", surface=_principled(alpha=0.0)), "transparent"),
    (_material("Ghost", surface=_node("BSDF_TRANSPARENT")), "transparent"),
    (_material("Mask", surface=_node("HOLDOUT")), "transparent"),
    (_material("Lit", surface=_principled(alpha=0.4)), None),
    (STONE, None),
    (_material("Empty"), None),
])
def test_material_kind(material, kind):
    assert visuals.material_kind(material) == kind


def test_meshes_left_out_and_the_ones_kept(make_obj):
    haze = _mesh(make_obj, "arena_atmosphere_Perimeter_Haze_00", HAZE)
    mixed = _mesh(make_obj, "Lantern", HAZE, STONE)  # one visible surface keeps it
    bare = _mesh(make_obj, "Box")  # no material: a default grey surface
    emitter = _mesh(make_obj, "Ash_Emitter", STONE, particles=1, show_emitter=False)
    shown = _mesh(make_obj, "Grass_Emitter", STONE, particles=1, show_emitter=True)
    tagged = _mesh(make_obj, "Fog_Wall", HAZE)
    tagged[ROLE_PROP] = "decor"  # the user decided
    kept, excluded = visuals.split_visible([haze, mixed, bare, emitter, shown, tagged, make_obj("Root", "EMPTY")])
    assert [o.name for o in kept] == ["Lantern", "Box", "Grass_Emitter", "Fog_Wall", "Root"]
    assert excluded == [{"object": "arena_atmosphere_Perimeter_Haze_00", "reason": "volume-only material"},
                        {"object": "Ash_Emitter", "reason": "particle emitter shown only as its particles"}]


def test_a_part_covered_by_an_ancestor_tag_is_still_left_out(make_obj):
    root = make_obj("Arena_Atmosphere_Root", "EMPTY")
    root[ROLE_PROP] = "static"
    haze = _mesh(make_obj, "Haze", HAZE)
    haze.parent = root
    assert visuals.non_visual_reason(haze) == "volume-only material"


def test_procedural_base_colours_are_reported(make_obj, monkeypatch):
    from mixar.modules.space_mixie_chat.core import export_emission
    image = types.SimpleNamespace(type="TEX_IMAGE", image=object(), inputs=Sockets())
    procedural = _material("ArenaDetail_DistantStone", surface=_principled(base=_node("MIX_RGB")))
    textured = _material("Basalt", surface=_principled(base=image))
    monkeypatch.setattr(export_emission, "upstream_images",
                        lambda socket: [socket.links[0].from_node] if socket.links[0].from_node is image else [])
    objects = [_mesh(make_obj, "Tower", procedural), _mesh(make_obj, "Floor", textured, STONE),
               _mesh(make_obj, "Tower_2", procedural)]
    assert visuals.procedural_materials(objects) == ["ArenaDetail_DistantStone"]
