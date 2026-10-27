# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Portable AxF car paint material built from stock Blender nodes only.

Renders in any Blender (Cycles and EEVEE) without the native AxF BSDF, at the
cost of exactness: stock nodes cannot see the light direction. The closures are
fitted per view angle by approx_fit.fit(); the AxF harness scores the result.
"""

from __future__ import annotations

import math
import os
import tempfile

import bpy
import numpy as np

from .approx_fit import N_VIEW, fit
from .blender_import import _flake_coordinates, _packed_data_image
from .cpa2_reader import read_cpa2


def _lut_rows(f: dict) -> np.ndarray:
    lut = np.zeros((3, N_VIEW, 4), np.float32)
    lut[0, :, :3] = f["Cd"]
    lut[1, :, :3] = f["Cs"]
    lut[2, :, 0] = np.sqrt(f["a_s"])                  # Blender roughness = sqrt(alpha)
    lut[2, :, 1] = f.get("g_f", np.zeros(N_VIEW))
    lut[..., 3] = 1.0
    return lut


def build_approx_material(path: str, *, name: str | None = None) -> bpy.types.Material:
    m = read_cpa2(path, load_flakes=True)
    f = fit(m)
    base = name or f"AxF {m['name']} (portable)"
    with tempfile.TemporaryDirectory(prefix="mixar_axf_approx_") as tmp:
        lut_img = _packed_data_image(f"{base} LUT", _lut_rows(f), tmp)
        flake_img = None
        if f["flake_rows"]:
            tiles = f["flake_tiles"]                      # (rows + 1, V, U, 3)
            n, h, w, _ = tiles.shape
            atlas = np.ones((h, n * w, 4), np.float32)
            for i in range(n):
                atlas[:, i * w:(i + 1) * w, :3] = tiles[i]
            flake_img = _packed_data_image(f"{base} Flakes", atlas, tmp)

    mat = bpy.data.materials.new(base)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N = nt.nodes
    L = nt.links.new

    def node(kind, x, y, **props):
        n = N.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math_node(op, a, b=None, x=0, y=0, clamp=False):
        n = node("ShaderNodeMath", x, y, operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L(v, n.inputs[i])
        return n.outputs[0]

    out = node("ShaderNodeOutputMaterial", 1400, 0)
    geo = node("ShaderNodeNewGeometry", -1400, 200)
    dot = node("ShaderNodeVectorMath", -1200, 200, operation='DOT_PRODUCT')
    L(geo.outputs["Normal"], dot.inputs[0]); L(geo.outputs["Incoming"], dot.inputs[1])
    cos_v = math_node('MAXIMUM', dot.outputs["Value"], 0.0, -1050, 200)
    theta_v = math_node('ARCCOSINE', math_node('MINIMUM', cos_v, 1.0, -950, 200), None, -850, 200)
    u_view = math_node('DIVIDE', theta_v, math.pi / 2, -700, 200)

    def lut_row(row, y):
        comb = node("ShaderNodeCombineXYZ", -550, y)
        L(u_view, comb.inputs[0])
        comb.inputs[1].default_value = (row + 0.5) / 3.0
        tex = node("ShaderNodeTexImage", -380, y, image=lut_img, interpolation='Linear',
                   extension='EXTEND')
        L(comb.outputs[0], tex.inputs["Vector"])
        return tex

    t_cd, t_cs, t_par = lut_row(0, 450), lut_row(1, 200), lut_row(2, -50)
    sep = node("ShaderNodeSeparateColor", -150, -50)
    L(t_par.outputs["Color"], sep.inputs[0])

    diffuse = node("ShaderNodeBsdfDiffuse", 150, 450)
    L(t_cd.outputs["Color"], diffuse.inputs["Color"])
    spec = node("ShaderNodeBsdfAnisotropic", 150, 200, distribution='BECKMANN')
    L(t_cs.outputs["Color"], spec.inputs["Color"])
    L(sep.outputs[0], spec.inputs["Roughness"])
    add = node("ShaderNodeAddShader", 450, 300)
    L(diffuse.outputs[0], add.inputs[0]); L(spec.outputs[0], add.inputs[1])
    base_out = add.outputs[0]

    if flake_img is not None:
        rows = f["flake_rows"]
        patch_m = (m["patch_mm"][0] or 25.6) / 1000.0
        flake_uv = _flake_coordinates(nt, patch_m, -1100, -600)
        sep_uv = node("ShaderNodeSeparateXYZ", -400, -600)
        L(flake_uv, sep_uv.inputs[0])
        fu = math_node('FRACT', sep_uv.outputs[0], None, -250, -560)
        fv = math_node('FRACT', sep_uv.outputs[1], None, -250, -640)
        ior = m["ior"] if m["refractive"] else 1.0
        theta_r = math_node('ARCSINE', math_node('DIVIDE', math_node('SINE', theta_v, None, -700, -300),
                                                  ior, -600, -300), None, -500, -300)
        bd = math_node('MULTIPLY', theta_r, m["num_theta_f"] * 2 / math.pi, -400, -300)
        d0 = math_node('FLOOR', bd, None, -300, -300)
        wd = math_node('SUBTRACT', bd, d0, -200, -360)

        def flake_tap(index, y):
            idx = math_node('MINIMUM', index, float(rows), -150, y)
            x = math_node('DIVIDE', math_node('ADD', idx, fu, -50, y), float(rows + 1), 50, y)
            comb = node("ShaderNodeCombineXYZ", 150, y)
            L(x, comb.inputs[0]); L(fv, comb.inputs[1])
            tex = node("ShaderNodeTexImage", 300, y, image=flake_img, interpolation='Closest',
                       extension='EXTEND')
            L(comb.outputs[0], tex.inputs["Vector"])
            return tex.outputs["Color"]

        c0 = flake_tap(d0, -500)
        c1 = flake_tap(math_node('ADD', d0, 1.0, -250, -700), -760)
        mix = node("ShaderNodeMix", 550, -600, data_type='RGBA', blend_type='MIX')
        L(wd, mix.inputs["Factor"]); L(c0, mix.inputs[6]); L(c1, mix.inputs[7])
        gain = node("ShaderNodeMix", 700, -600, data_type='RGBA', blend_type='MULTIPLY')
        gain.inputs["Factor"].default_value = 1.0
        L(mix.outputs[2], gain.inputs[6])
        g_rgb = node("ShaderNodeCombineColor", 550, -800)
        for i in range(3):
            L(sep.outputs[1], g_rgb.inputs[i])
        L(g_rgb.outputs[0], gain.inputs[7])
        sparkle = node("ShaderNodeBsdfAnisotropic", 900, -600, distribution='BECKMANN')
        L(sep.outputs[0], sparkle.inputs["Roughness"])   # same lobe width as the specular
        L(gain.outputs[2], sparkle.inputs["Color"])
        add2 = node("ShaderNodeAddShader", 900, 300)
        L(base_out, add2.inputs[0]); L(sparkle.outputs[0], add2.inputs[1])
        base_out = add2.outputs[0]

    fres = node("ShaderNodeFresnel", 900, 500)
    fres.inputs["IOR"].default_value = m["ior"]
    mirror = node("ShaderNodeBsdfAnisotropic", 900, 100, distribution='GGX')
    mirror.inputs["Roughness"].default_value = 0.0
    mirror.inputs["Color"].default_value = (1, 1, 1, 1)
    coat = node("ShaderNodeMixShader", 1150, 300)
    L(fres.outputs[0], coat.inputs[0]); L(base_out, coat.inputs[1]); L(mirror.outputs[0], coat.inputs[2])
    L(coat.outputs[0], out.inputs["Surface"])
    mat["axf_source_name"] = os.path.basename(path)
    mat["axf_portable"] = True
    return mat
