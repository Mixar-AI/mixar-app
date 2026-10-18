# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""glTF has no emission-strength texture. A material whose Emission
Strength is a mask (× k) exported as ``colour × k`` everywhere, so the
boss's whole armour glowed instead of its lava cracks.
``export_emission.baked_emission_masks`` bakes ``colour × mask`` into the
emissive colour for the export, then restores the material and frees the
image."""

import types
from pathlib import Path

import numpy as np
import pytest

from mixar.modules.space_mixie_chat.core import export_emission as em

CORE = Path(__file__).parents[1] / "src/scripts/mixar/modules/space_mixie_chat/core"


# --- a tiny node graph --------------------------------------------------------

class Link:
    def __init__(self, from_socket, to_socket):
        self.from_socket, self.to_socket = from_socket, to_socket
        self.from_node = from_socket.node


class Socket:
    def __init__(self, node, name, value=0.0):
        self.node, self.name, self.identifier, self.default_value = node, name, name, value
        self.links = []

    @property
    def is_linked(self):
        return bool(self.links)


class Sockets(list):
    def get(self, name, default=None):
        return next((s for s in self if s.name == name), default)

    def __getitem__(self, key):
        return self.get(key) if isinstance(key, str) else list.__getitem__(self, key)


class Node:
    def __init__(self, type_, name="", inputs=(), outputs=(), **attrs):
        self.type, self.name = type_, name or type_
        self.inputs = Sockets(Socket(self, n, v) for n, v in inputs)
        self.outputs = Sockets(Socket(self, n) for n in outputs)
        self.__dict__.update(attrs)


class Links(list):
    def new(self, from_socket, to_socket):
        for old in list(to_socket.links):
            self.remove(old)
        link = Link(from_socket, to_socket)
        to_socket.links.append(link)
        self.append(link)
        return link

    def remove(self, link):
        link.to_socket.links.remove(link)
        list.remove(self, link)


class Tree:
    def __init__(self, nodes):
        self.nodes = Nodes(nodes)
        self.links = Links()


class Nodes(list):
    def new(self, kind):
        node = Node("TEX_IMAGE", kind, inputs=[("Vector", None)], outputs=["Color", "Alpha"],
                    image=None, interpolation="Linear", extension="REPEAT")
        self.append(node)
        return node


def _image(name, colorspace="sRGB"):
    return types.SimpleNamespace(name=name, colorspace_settings=types.SimpleNamespace(name=colorspace),
                                 is_float=False, size=(2, 2))


def _boss_material(op="MULTIPLY", k=5.0):
    """Principled with Emission Color ← group(colour image), Emission
    Strength ← Math(mask × k), like the user's Boss_Body."""
    colour = Node("TEX_IMAGE", "base", inputs=[("Vector", None)], outputs=["Color", "Alpha"],
                  image=_image("Boss_Body_basecolor"))
    inner_out = Node("GROUP_OUTPUT", inputs=[("Color", None)])
    inner = Tree([colour, inner_out])
    inner.links.new(colour.outputs["Color"], inner_out.inputs["Color"])
    group = Node("GROUP", "Group", outputs=["Color"], node_tree=inner)
    uv = Node("UVMAP", "uv", outputs=["UV"], uv_map="UV Map")
    mask = Node("TEX_IMAGE", "mask", inputs=[("Vector", None)], outputs=["Color", "Alpha"],
                image=_image("lava_mask", "Non-Color"), interpolation="Linear", extension="REPEAT")
    math = Node("MATH", "strength", inputs=[("Value", 0.5), ("Value", k), ("Value", 0.5)], outputs=["Value"],
                operation=op, use_clamp=False)
    bsdf = Node("BSDF_PRINCIPLED", "bsdf", inputs=[("Emission Color", None), ("Emission Strength", 0.0)],
                outputs=["BSDF"])
    out = Node("OUTPUT_MATERIAL", inputs=[("Surface", None)], is_active_output=True)
    tree = Tree([group, uv, mask, math, bsdf, out])
    tree.links.new(uv.outputs["UV"], mask.inputs["Vector"])
    tree.links.new(mask.outputs["Color"], math.inputs[0])
    tree.links.new(math.outputs["Value"], bsdf.inputs["Emission Strength"])
    tree.links.new(group.outputs["Color"], bsdf.inputs["Emission Color"])
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return types.SimpleNamespace(name="Boss_Body", node_tree=tree), bsdf, math


# --- detection ------------------------------------------------------------------

def test_detects_mask_times_constant_and_resolves_the_colour_through_the_group():
    material, bsdf, _math = _boss_material()
    mask_node, socket, k = em.strength_mask(bsdf)
    assert mask_node.name == "mask" and socket.name == "Color" and k == 5.0  # input 3 is unused
    mesh = types.SimpleNamespace(data=types.SimpleNamespace(uv_layers=[types.SimpleNamespace(name="UV Map")]))
    plan = em._plan(material, [mesh])
    assert plan[1].name == "mask" and plan[3] == 5.0 and plan[4].image.name == "Boss_Body_basecolor"


def test_other_strength_graphs_are_left_alone():
    _material, bsdf, math = _boss_material(op="ADD")
    assert em.strength_mask(bsdf) is None
    _material, bsdf, math = _boss_material()
    math.use_clamp = True
    assert em.strength_mask(bsdf) is None
    material, bsdf, math = _boss_material()
    two_uvs = types.SimpleNamespace(data=types.SimpleNamespace(
        uv_layers=[types.SimpleNamespace(name="UV Map"), types.SimpleNamespace(name="Lava")]))
    tree = material.node_tree
    tree.nodes[1].uv_map = "Lava"  # the mask reads another UV map than the colour
    assert em._plan(material, [two_uvs]) == "the mask and the colour use different UV maps"


# --- pixels -------------------------------------------------------------------------

def test_baked_pixels_multiply_in_linear_light():
    grey = 0.5  # sRGB 0.5 = linear 0.214
    colour = np.full((2, 2, 4), grey, np.float32)
    mask = np.zeros((2, 2, 4), np.float32)
    mask[0, 0, :3], mask[0, 1, :3], mask[1, 0, :3] = 1.0, 0.5, 0.0
    out = em.baked_pixels(colour, True, mask, "Color", False)
    linear = em._to_linear(out[..., :3])
    grey_linear = float(em._to_linear(np.float32(grey)))
    assert np.allclose(linear[0, 0], grey_linear, atol=1e-4)
    assert np.allclose(linear[0, 1], 0.5 * grey_linear, atol=1e-4)
    assert np.allclose(out[1, 0, :3], 0.0) and np.all(out[..., 3] == 1.0)
    small = np.ones((1, 1, 4), np.float32)  # a mask of another size is resampled
    assert em.baked_pixels(colour, True, small, "Alpha", False).shape == colour.shape


# --- the swap is temporary --------------------------------------------------------------

def test_bakes_for_the_export_then_restores_and_frees(monkeypatch):
    material, bsdf, math = _boss_material()
    created, removed = [], []

    class Images:
        def new(self, name, w, h, alpha=False):
            image = types.SimpleNamespace(name=name, size=(w, h), colorspace_settings=types.SimpleNamespace(name=""),
                                          pixels=types.SimpleNamespace(foreach_set=lambda data: None))
            created.append(image)
            return image

        def remove(self, image):
            removed.append(image)

    monkeypatch.setattr(em, "bpy", types.SimpleNamespace(data=types.SimpleNamespace(images=Images())))
    monkeypatch.setattr(em, "_pixels", lambda image: np.full((2, 2, 4), 0.5, np.float32))
    mesh = types.SimpleNamespace(data=types.SimpleNamespace(
        materials=[material], uv_layers=[types.SimpleNamespace(name="UV Map")]))
    nodes_before = len(material.node_tree.nodes)
    with em.baked_emission_masks([mesh]) as (baked, notes):
        assert baked == ["Boss_Body"] and notes == []
        source = bsdf.inputs["Emission Color"].links[0].from_node
        assert source.image is created[0] and source.inputs["Vector"].links[0].from_node.name == "uv"
        assert not bsdf.inputs["Emission Strength"].is_linked
        assert bsdf.inputs["Emission Strength"].default_value == 5.0
    assert bsdf.inputs["Emission Color"].links[0].from_node.name == "Group"
    assert bsdf.inputs["Emission Strength"].links[0].from_node is math
    assert bsdf.inputs["Emission Strength"].default_value == 0.0
    assert len(material.node_tree.nodes) == nodes_before and removed == created


def test_only_gltf_exports_bake():
    source = (CORE / "agent_export.py").read_text(encoding="utf-8")
    assert 'baked_emission_masks(meshes) if fmt in ("glb", "gltf")' in source
    assert "emission_ctx as (_baked, emission_notes)" in source
