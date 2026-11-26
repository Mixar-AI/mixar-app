# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The "AxF Box Projection" node group: flake and coat coordinates for a mesh without UVs.

Object-space position projected on the dominant normal axis (metres), and the
world-space direction of increasing u (the tangent the coat normal map needs).

One projection per point (no blending), so flake statistics stay exactly the measured
ones. u is mirrored where needed so (tangent, normal x tangent, normal) is right handed
on every face, which keeps the clear coat normal map a true surface. Object scale is
assumed to be 1 (metres).

z-dominant: (u, v) = (s Px, Py); x-dominant: (s Py, Pz); y-dominant: (s Px, Pz),
with s = sign(nz), sign(nx), -sign(ny).

The maths lives in one shared node group so a material shows a single node instead of
about thirty. The group is rebuilt only when its version tag is missing or older, so a
library or file that already holds it keeps using the same data-block.
"""

from __future__ import annotations

import bpy

GROUP_NAME = "AxF Box Projection"
GROUP_VERSION = 1
_VERSION_KEY = "axf_box_projection_version"
OUT_UV = "UV"
OUT_TANGENT = "Tangent"


def _build(ng) -> None:
    nodes, links = ng.nodes, ng.links
    nodes.clear()
    for item in list(ng.interface.items_tree):
        ng.interface.remove(item)
    ng.interface.new_socket(OUT_UV, in_out='OUTPUT', socket_type='NodeSocketVector',
                            description="Object position on the dominant face, in metres")
    ng.interface.new_socket(OUT_TANGENT, in_out='OUTPUT', socket_type='NodeSocketVector',
                            description="World-space direction of increasing U")

    tc = nodes.new("ShaderNodeTexCoord"); tc.location = (-900, 0)
    sp = nodes.new("ShaderNodeSeparateXYZ"); sp.location = (-700, 120)
    sn = nodes.new("ShaderNodeSeparateXYZ"); sn.location = (-700, -120)
    links.new(tc.outputs["Object"], sp.inputs[0])
    links.new(tc.outputs["Normal"], sn.inputs[0])

    def math(op, a, b=None, loc=(0, 0)):
        n = nodes.new("ShaderNodeMath"); n.operation = op; n.location = loc
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]

    ax = math('ABSOLUTE', sn.outputs[0], loc=(-500, -60))
    ay = math('ABSOLUTE', sn.outputs[1], loc=(-500, -120))
    az = math('ABSOLUTE', sn.outputs[2], loc=(-500, -180))
    z_ge_x = math('GREATER_THAN', az, ax, loc=(-330, -60))
    z_ge_y = math('GREATER_THAN', az, ay, loc=(-330, -120))
    z_dom = math('MULTIPLY', z_ge_x, z_ge_y, loc=(-180, -90))
    x_ge_y = math('GREATER_THAN', ax, ay, loc=(-330, -180))
    not_z = math('SUBTRACT', 1.0, z_dom, loc=(-180, -150))
    x_dom = math('MULTIPLY', not_z, x_ge_y, loc=(-60, -150))
    y_dom = math('SUBTRACT', not_z, x_dom, loc=(-60, -210))
    # s = sign of the dominant component (negated for y) -> right-handed frames.
    sx = math('SIGN', sn.outputs[0], loc=(-330, -260))
    sy = math('SIGN', sn.outputs[1], loc=(-330, -300))
    sz = math('SIGN', sn.outputs[2], loc=(-330, -340))
    s = math('ADD', math('MULTIPLY', z_dom, sz, loc=(-180, -260)),
             math('SUBTRACT', math('MULTIPLY', x_dom, sx, loc=(-180, -300)),
                  math('MULTIPLY', y_dom, sy, loc=(-180, -340)), loc=(-60, -320)),
             loc=(60, -290))
    # u = s * (Py if x-dominant else Px); v = Py if z-dominant else Pz
    one_minus_x = math('SUBTRACT', 1.0, x_dom, loc=(60, 60))
    u_base = math('ADD', math('MULTIPLY', one_minus_x, sp.outputs[0], loc=(180, 60)),
                  math('MULTIPLY', x_dom, sp.outputs[1], loc=(180, 0)), loc=(300, 30))
    u = math('MULTIPLY', s, u_base, loc=(420, 30))
    v = math('ADD', math('MULTIPLY', z_dom, sp.outputs[1], loc=(180, -60)),
             math('MULTIPLY', not_z, sp.outputs[2], loc=(180, -120)), loc=(300, -90))
    comb = nodes.new("ShaderNodeCombineXYZ"); comb.location = (540, 0)
    links.new(u, comb.inputs[0]); links.new(v, comb.inputs[1])

    # Tangent (object space) = s * (Y if x-dominant else X), then to world space.
    tan = nodes.new("ShaderNodeCombineXYZ"); tan.location = (540, -260)
    links.new(math('MULTIPLY', s, one_minus_x, loc=(420, -230)), tan.inputs[0])
    links.new(math('MULTIPLY', s, x_dom, loc=(420, -290)), tan.inputs[1])
    vt = nodes.new("ShaderNodeVectorTransform"); vt.location = (700, -260)
    vt.vector_type = 'VECTOR'; vt.convert_from = 'OBJECT'; vt.convert_to = 'WORLD'
    links.new(tan.outputs[0], vt.inputs[0])

    out = nodes.new("NodeGroupOutput"); out.location = (900, -100)
    links.new(comb.outputs[0], out.inputs[OUT_UV])
    links.new(vt.outputs[0], out.inputs[OUT_TANGENT])
    ng[_VERSION_KEY] = GROUP_VERSION


def box_projection_group():
    """The shared node group, created or brought up to date on first use."""
    for ng in bpy.data.node_groups:
        if ng.bl_idname == "ShaderNodeTree" and ng.get(_VERSION_KEY) == GROUP_VERSION \
                and ng.name.split(".")[0] == GROUP_NAME and not ng.library:
            return ng
    ng = bpy.data.node_groups.new(GROUP_NAME, "ShaderNodeTree")
    _build(ng)
    return ng


def add_box_projection(nt, x: float, y: float, *, tangent: bool = True):
    """Add one "AxF Box Projection" group node to nt. Returns (uv_metres, tangent or None)."""
    node = nt.nodes.new("ShaderNodeGroup")
    node.node_tree = box_projection_group()
    node.label = GROUP_NAME
    node.location = (x - 200, y)
    node.width = 180
    return node.outputs[OUT_UV], (node.outputs[OUT_TANGENT] if tangent else None)
