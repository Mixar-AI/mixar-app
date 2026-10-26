# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which materials an export bakes to images, and at what size.

The glTF / FBX / USD exporters read a Principled BSDF fed by image textures or
plain values; anything else in front of an input arrives flat in a game
engine, so ``export_bake.plan`` marks it for a bake.
"""

import types

from mixar.modules.space_mixie_chat.core import export_bake


class _Socket:
    def __init__(self, name, value=0.0):
        self.name = name
        self.default_value = value
        self.links = []

    @property
    def is_linked(self):
        return bool(self.links)


class _Sockets(list):
    def get(self, name):
        return next((s for s in self if s.name == name), None)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.get(key)
        return list.__getitem__(self, key)


class _Node:
    def __init__(self, idname, inputs=(), type_=""):
        self.bl_idname = idname
        self.type = type_
        self.inputs = _Sockets(_Socket(n) for n in inputs)
        self.outputs = _Sockets([_Socket("out")])


def _link(src, dst_socket):
    dst_socket.links.append(types.SimpleNamespace(from_node=src, from_socket=src.outputs[0], is_muted=False))


def _material(surface=None):
    out = _Node("ShaderNodeOutputMaterial", ("Surface",), "OUTPUT_MATERIAL")
    bsdf = _Node("ShaderNodeBsdfPrincipled", [c for c, _, _ in export_bake.CHANNELS] + ["Emission Strength"])
    _link(surface or bsdf, out.inputs["Surface"])
    tree = types.SimpleNamespace(nodes=[out, bsdf], get_output_node=lambda target: out)
    return types.SimpleNamespace(node_tree=tree), bsdf


def test_plain_values_and_image_chains_are_not_baked():
    mat, _ = _material()
    assert export_bake.plan(mat) is None
    mat, bsdf = _material()
    image = _Node("ShaderNodeTexImage", ("Vector",))
    _link(_Node("ShaderNodeMapping", ("Vector",)), image.inputs["Vector"])
    _link(image, bsdf.inputs["Base Color"])
    normal = _Node("ShaderNodeNormalMap", ("Color",))
    _link(_Node("ShaderNodeTexImage", ("Vector",)), normal.inputs["Color"])
    _link(normal, bsdf.inputs["Normal"])
    assert export_bake.plan(mat) is None


def test_a_procedural_input_bakes_every_linked_channel():
    mat, bsdf = _material()
    _link(_Node("ShaderNodeTexImage", ("Vector",)), bsdf.inputs["Base Color"])
    ramp = _Node("ShaderNodeValToRGB", ("Fac",))
    _link(_Node("ShaderNodeTexNoise", ("Vector",)), ramp.inputs["Fac"])
    _link(ramp, bsdf.inputs["Roughness"])
    assert export_bake.plan(mat) == {"mode": "principled", "channels": ["Base Color", "Roughness"]}


def test_a_bump_is_procedural_and_dark_emission_is_dropped():
    mat, bsdf = _material()
    _link(_Node("ShaderNodeBump", ("Height",)), bsdf.inputs["Normal"])
    _link(_Node("ShaderNodeTexNoise", ("Vector",)), bsdf.inputs["Emission Color"])
    assert export_bake.plan(mat) == {"mode": "principled", "channels": ["Normal"]}
    bsdf.inputs["Emission Strength"].default_value = 2.0
    assert export_bake.plan(mat)["channels"] == ["Emission Color", "Normal"]


def test_an_unbaked_paint_stack_group_is_baked():
    mat, bsdf = _material()
    _link(_Node("ShaderNodeGroup"), bsdf.inputs["Base Color"])
    assert export_bake.plan(mat)["channels"] == ["Base Color"]


def test_a_surface_that_is_not_principled_bakes_colour_roughness_normal():
    mix = _Node("ShaderNodeMixShader", ("Fac",))
    mat, _ = _material(surface=mix)
    assert export_bake.plan(mat) == {"mode": "surface", "channels": ["Base Color", "Roughness", "Normal"]}


def test_no_surface_or_no_tree_is_left_alone():
    assert export_bake.plan(None) is None
    assert export_bake.plan(types.SimpleNamespace(node_tree=None)) is None


def test_texture_size_follows_area_within_bounds():
    assert export_bake.texture_size(0.0) == 256
    assert export_bake.texture_size(24.0) == 1024  # a 2 m cube at 128 px/m
    assert export_bake.texture_size(400.0) == 2048  # capped
    assert export_bake.texture_size(400.0, hi=4096) == 4096
