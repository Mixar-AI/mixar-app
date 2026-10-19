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


# --- particle fields default to decor --------------------------------------------------

import numpy as np  # noqa: E402

from mixar.modules.game_studio.core import exporter  # noqa: E402


class _Seq:
    def __init__(self, data, width):
        self.data, self.width = np.asarray(data), width

    def __len__(self):
        return self.data.shape[0]

    def foreach_get(self, _name, out):
        out[:] = self.data.ravel()


def _fake_mesh(parts):
    """``parts`` = list of (centre, size): one octahedron each."""
    co, edges, areas = [], [], []
    for (cx, cy, cz), r in parts:
        base = len(co)
        co += [(cx + r, cy, cz), (cx - r, cy, cz), (cx, cy + r, cz), (cx, cy - r, cz), (cx, cy, cz + r), (cx, cy, cz - r)]
        edges += [(base + a, base + b) for a, b in ((0, 2), (2, 1), (1, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4),
                                                   (0, 5), (1, 5), (2, 5), (3, 5))]
        areas += [0.866 * (r * 1.414) ** 2] * 8
    mesh = types.SimpleNamespace(vertices=_Seq(co, 3), edges=_Seq(edges, 2), polygons=_Seq(areas, 1))
    mesh.as_pointer = lambda: id(mesh)
    return mesh


def _field(n=65, span=33.0, size=0.04):
    rng = np.random.default_rng(1)
    return [((float(x), float(y), float(z)), size) for x, y, z in rng.uniform(0, span, (n, 3)) * [1, 1, 0.1]]


def test_particle_field_detection():
    visuals._field_cache.clear()
    assert visuals.is_particle_field(_fake_mesh(_field()))  # the temple's ash: 65 bits over 33 m
    assert not visuals.is_particle_field(_fake_mesh(_field(n=12)))  # too few parts
    assert not visuals.is_particle_field(_fake_mesh(_field(size=2.0)))  # parts too big (rubble)
    one = _fake_mesh([((0.0, 0.0, 0.0), 1.0)])
    assert not visuals.is_particle_field(one)


def test_fields_play_as_decor_unless_tagged(make_obj, make_scene):
    visuals._field_cache.clear()
    ash = _mesh(make_obj, "arena_atmosphere_Ash", STONE)
    ash.data = _fake_mesh(_field())
    ash.data.materials = [STONE]
    rock = _mesh(make_obj, "Rock", STONE)
    rock.data = _fake_mesh([((0.0, 0.0, 0.0), 1.0)])
    rock.data.materials = [STONE]
    assert visuals.particle_fields([ash, rock]) == [
        {"object": "arena_atmosphere_Ash", "reason": "particle field (many tiny loose parts)"}]
    hazard_root = make_obj("Lava_Root", "EMPTY")
    hazard_root[ROLE_PROP] = "hazard"
    embers = _mesh(make_obj, "Embers", STONE)
    embers.data, embers.parent = _fake_mesh(_field()), hazard_root
    embers.data.materials = [STONE]
    assert visuals.particle_fields([embers]) == []  # a hazard keeps its role
    ash[ROLE_PROP] = "static"
    assert visuals.particle_fields([ash]) == []  # the user decided


def test_the_spec_lists_a_field_as_a_decor_node(make_obj, make_scene, monkeypatch):
    visuals._field_cache.clear()
    root = make_obj("Temple_Arena_Root", "EMPTY")
    root[ROLE_PROP] = "static"
    ash = _mesh(make_obj, "arena_atmosphere_Ash", STONE)
    ash.data, ash.parent = _fake_mesh(_field()), root
    ash.data.materials = [STONE]
    floor = _mesh(make_obj, "Floor", STONE)
    monkeypatch.setattr(exporter, "app_version", lambda: "")
    spec, _objects = exporter.current_spec(make_scene([root, ash, floor]))
    assert {n["name"]: n["role"] for n in spec["nodes"]} == {
        "Temple_Arena_Root": "static", "arena_atmosphere_Ash": "decor", "Floor": "static"}
    assert next(n for n in spec["nodes"] if n["name"] == "arena_atmosphere_Ash")["subtree"] is True
