# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Solid realization: analytic primitives + exact-solver CSG booleans.

Every face of a realized part is a plane or a cylinder/cone facet, so edges
stay sharp at any resolution — the whole point of the shape-as-code
representation. Primitives are generated as raw vert/face lists (pure math,
baked local transforms), then combined SEQUENTIALLY with Blender's EXACT
boolean solver via the data API (no bpy.ops, no context dependence).
"""

from __future__ import annotations

import math

import bpy

MAX_BOOLEAN_FACES = 250_000  # refuse runaway parts before they freeze Blender


# ---------------------------------------------------------------------------
# Primitive vert/face generation (local space, +Z up unless an axis is given)
# ---------------------------------------------------------------------------


def _rot_matrix(rx: float, ry: float, rz: float):
    """Euler XYZ (degrees) -> 3x3 row-major rotation."""
    ax, ay, az = (math.radians(a) for a in (rx, ry, rz))
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    # R = Rz @ Ry @ Rx (Blender euler XYZ convention: X applied first)
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


_AXIS_ROT = {"Z": (0, 0, 0), "X": (0, 90, 0), "Y": (-90, 0, 0)}


def _apply_transform(verts, at, rot, axis="Z"):
    ar = _AXIS_ROT.get(str(axis).upper(), (0, 0, 0))
    m1 = _rot_matrix(*ar)
    m2 = _rot_matrix(*(rot or (0.0, 0.0, 0.0)))
    tx, ty, tz = at or (0.0, 0.0, 0.0)
    out = []
    for v in verts:
        # axis alignment first, then the user rotation, then translation
        p = (
            m1[0][0] * v[0] + m1[0][1] * v[1] + m1[0][2] * v[2],
            m1[1][0] * v[0] + m1[1][1] * v[1] + m1[1][2] * v[2],
            m1[2][0] * v[0] + m1[2][1] * v[1] + m1[2][2] * v[2],
        )
        out.append((
            m2[0][0] * p[0] + m2[0][1] * p[1] + m2[0][2] * p[2] + tx,
            m2[1][0] * p[0] + m2[1][1] * p[1] + m2[1][2] * p[2] + ty,
            m2[2][0] * p[0] + m2[2][1] * p[1] + m2[2][2] * p[2] + tz,
        ))
    return out


def gen_box(sx, sy, sz):
    x, y, z = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    return verts, faces


def gen_wedge(sx, sy, sz):
    """Right-triangular prism: a box whose +Y top edge is collapsed (ramp
    rising toward -Y). Length X, depth Y, height Z."""
    x, y, z = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z),
    ]
    faces = [(0, 3, 2, 1), (0, 1, 5, 4), (1, 2, 5), (3, 0, 4), (2, 3, 4, 5)]
    return verts, faces


def gen_cylinder(d, h, segments):
    return gen_cone(d, d, h, segments)


def gen_cone(d_bottom, d_top, h, segments):
    """Frustum along +Z, centered (z in [-h/2, h/2]). d_top 0 => apex."""
    n = max(3, int(segments))
    rb, rt = d_bottom / 2.0, d_top / 2.0
    hz = h / 2.0
    verts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        verts.append((rb * math.cos(a), rb * math.sin(a), -hz))
    apex = rt < 1e-9
    if apex:
        verts.append((0.0, 0.0, hz))
        top = [len(verts) - 1] * n
    else:
        for i in range(n):
            a = 2.0 * math.pi * i / n
            verts.append((rt * math.cos(a), rt * math.sin(a), hz))
        top = list(range(n, 2 * n))
    faces = []
    for i in range(n):
        j = (i + 1) % n
        if apex:
            faces.append((i, j, top[0]))
        else:
            faces.append((i, j, top[j], top[i]))
    faces.append(tuple(reversed(range(n))))          # bottom cap
    if not apex:
        faces.append(tuple(top))                     # top cap
    return verts, faces


def gen_tube(d_outer, d_inner, h, segments):
    """Hollow cylinder (annular ring) along +Z, centered."""
    n = max(3, int(segments))
    ro, ri = d_outer / 2.0, max(1e-6, d_inner / 2.0)
    hz = h / 2.0
    verts = []
    for r, z in ((ro, -hz), (ro, hz), (ri, -hz), (ri, hz)):
        for i in range(n):
            a = 2.0 * math.pi * i / n
            verts.append((r * math.cos(a), r * math.sin(a), z))
    ob, ot, ib, it_ = 0, n, 2 * n, 3 * n
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((ob + i, ob + j, ot + j, ot + i))      # outer wall
        faces.append((ib + j, ib + i, it_ + i, it_ + j))    # inner wall
        faces.append((ob + j, ob + i, ib + i, ib + j))      # bottom annulus
        faces.append((ot + i, ot + j, it_ + j, it_ + i))    # top annulus
    return verts, faces


def gen_sphere(d, segments, rings):
    n, m = max(3, int(segments)), max(2, int(rings))
    r = d / 2.0
    verts = [(0.0, 0.0, r)]
    for j in range(1, m):
        phi = math.pi * j / m
        z = r * math.cos(phi)
        rr = r * math.sin(phi)
        for i in range(n):
            a = 2.0 * math.pi * i / n
            verts.append((rr * math.cos(a), rr * math.sin(a), z))
    verts.append((0.0, 0.0, -r))
    last = len(verts) - 1
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((0, 1 + i, 1 + j))
    for ring in range(m - 2):
        a0 = 1 + ring * n
        b0 = 1 + (ring + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append((a0 + i, b0 + i, b0 + j, a0 + j))
    b0 = 1 + (m - 2) * n
    for i in range(n):
        j = (i + 1) % n
        faces.append((last, b0 + j, b0 + i))
    return verts, faces


def gen_torus(d_major, d_minor, seg_major, seg_minor):
    n, m = max(3, int(seg_major)), max(3, int(seg_minor))
    R, r = d_major / 2.0, d_minor / 2.0
    verts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        ca, sa = math.cos(a), math.sin(a)
        for j in range(m):
            b = 2.0 * math.pi * j / m
            rr = R + r * math.cos(b)
            verts.append((rr * ca, rr * sa, r * math.sin(b)))
    faces = []
    for i in range(n):
        i2 = (i + 1) % n
        for j in range(m):
            j2 = (j + 1) % m
            faces.append((i * m + j, i2 * m + j, i2 * m + j2, i * m + j2))
    return verts, faces


GENERATORS = {
    "box": lambda s: gen_box(*s["size"]),
    "wedge": lambda s: gen_wedge(*s["size"]),
    "cylinder": lambda s: gen_cylinder(s["d"], s["h"], s.get("segments", 48)),
    "cone": lambda s: gen_cone(s["d1"], s.get("d2", 0.0), s["h"], s.get("segments", 48)),
    "tube": lambda s: gen_tube(s["d_outer"], s["d_inner"], s["h"], s.get("segments", 48)),
    "sphere": lambda s: gen_sphere(s["d"], s.get("segments", 32), s.get("rings", 16)),
    "torus": lambda s: gen_torus(
        s["d_major"], s["d_minor"], s.get("segments", 48), s.get("minor_segments", 16)
    ),
}


# ---------------------------------------------------------------------------
# Mesh + boolean assembly (data API only)
# ---------------------------------------------------------------------------


def mesh_from_solid(name: str, solid: dict):
    """One solid spec -> a new Mesh datablock with its local transform baked."""
    gen = GENERATORS.get(solid["kind"])
    if gen is None:
        raise ValueError(f"unknown solid kind '{solid['kind']}'")
    verts, faces = gen(solid)
    verts = _apply_transform(
        verts, solid.get("at"), solid.get("rot"), solid.get("axis", "Z")
    )
    if solid.get("scale") and solid["scale"] != 1.0:
        f = float(solid["scale"])
        verts = [(v[0] * f, v[1] * f, v[2] * f) for v in verts]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], [list(f) for f in faces])
    mesh.update()
    return mesh


_BOOL_OPS = {"add": "UNION", "cut": "DIFFERENCE", "intersect": "INTERSECT"}


def _evaluated_mesh_swap(obj, scene):
    """Re-evaluate ``obj`` with its current modifiers and bake the result into
    a fresh mesh datablock (modifiers dropped). Data-API modifier apply."""
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    new_mesh = bpy.data.meshes.new_from_object(
        ev, preserve_all_data_layers=True, depsgraph=deps
    )
    old = obj.data
    obj.data = new_mesh
    for mod in list(obj.modifiers):
        obj.modifiers.remove(mod)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def boolean_with_mesh(obj, tool_mesh, op: str, scene, solver: str = "EXACT"):
    """Apply one boolean between ``obj`` and a raw tool mesh, in-place."""
    if len(obj.data.polygons) + len(tool_mesh.polygons) > MAX_BOOLEAN_FACES:
        raise RuntimeError("part exceeds the boolean face budget")
    tool = bpy.data.objects.new(obj.name + "_tool", tool_mesh)
    scene.collection.objects.link(tool)
    try:
        mod = obj.modifiers.new(name="_asm_bool", type="BOOLEAN")
        mod.operation = _BOOL_OPS[op]
        mod.object = tool
        try:
            mod.solver = solver
        except TypeError:
            pass  # older Blender without this solver id — keep default
        _evaluated_mesh_swap(obj, scene)
    finally:
        bpy.data.objects.remove(tool, do_unlink=True)
        if tool_mesh.users == 0:
            bpy.data.meshes.remove(tool_mesh)
    return obj


def realize_part_object(
    name: str, solids: list[dict], scene, solver: str = "EXACT",
    material_index_for_block=None,
):
    """Build one part object from its ordered solid list (local space).

    The first "add" solid seeds the mesh; every subsequent solid is combined
    with a boolean in PROGRAM ORDER (so a cut can precede later adds when the
    author wants it). ``material_index_for_block`` maps a solid's
    ``color_block`` tag to a material slot index — assigned on the tool mesh
    BEFORE the boolean so the block tags survive into the final faces.
    """
    obj = None
    for solid in solids:
        op = solid.get("op", "add")
        mesh = mesh_from_solid(f"{name}_solid", solid)
        if material_index_for_block is not None:
            idx = material_index_for_block(solid.get("color_block"))
            if idx:
                for poly in mesh.polygons:
                    poly.material_index = idx
        if obj is None:
            if op != "add":
                # A part must start from added material; ignore leading cuts.
                bpy.data.meshes.remove(mesh)
                continue
            obj = bpy.data.objects.new(name, mesh)
            scene.collection.objects.link(obj)
        else:
            boolean_with_mesh(obj, mesh, op, scene, solver=solver)
    if obj is None:
        raise ValueError(f"part '{name}' produced no solid geometry")
    return obj


def chamfer_object(obj, width: float, angle_deg: float, scene):
    """Machined chamfer: single-segment bevel limited by edge angle."""
    if width <= 0:
        return obj
    mod = obj.modifiers.new(name="_asm_chamfer", type="BEVEL")
    mod.width = float(width)
    mod.segments = 1
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(float(angle_deg))
    return _evaluated_mesh_swap(obj, scene)
