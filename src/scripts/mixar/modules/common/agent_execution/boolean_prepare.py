# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Conservative native Boolean preparation without changing source geometry."""


def bounds_overlap(points, axes):
    """False only when a separating projection proves ALL cutters disjoint.

    World AABBs are the cheap broad phase. For tilted cutters, also project
    onto each object's local axes (in world space) and their cross products.
    This is conservative for arbitrary nonconvex meshes, not just boxes:
    disjoint projections prove separation; overlapping ones prove nothing.
    """
    import numpy as np

    bounds = [(p.min(axis=0), p.max(axis=0)) for p in points]
    for i, a in enumerate(points):
        for j, b in enumerate(points[:i]):
            lo, hi = bounds[i]
            other_lo, other_hi = bounds[j]
            if np.any(hi < other_lo) or np.any(other_hi < lo):
                continue
            candidates = [*axes[i], *axes[j], *(np.cross(x, y) for x in axes[i] for y in axes[j])]
            separated = False
            for axis in candidates:
                length = np.linalg.norm(axis)
                if length <= 1e-12:
                    continue
                # Center first so precision depends on cutter size, not world offset.
                pa, pb = (a - a[0]) @ (axis / length), (b - a[0]) @ (axis / length)
                margin = 1e-7 * max(float(np.ptp(pa)), float(np.ptp(pb)), 1e-9)
                if pa.max() + margin < pb.min() or pb.max() + margin < pa.min():
                    separated = True
                    break
            if not separated:
                return True
    return False


def oriented_copy(mesh):
    """Return a repaired private mesh only for a single closed solid shell.

    Reorienting disconnected shells could fill an intentional inner cavity,
    so those retain Exact. No welding, remeshing, vertex edits or topology
    simplification occurs. BMesh reverses face-loop data together with faces.
    """
    import bpy
    import bmesh

    probe = mesh.copy()
    bm = bmesh.new()
    keep = False
    try:
        if probe.validate(clean_customdata=False):
            raise ValueError('Invalid Boolean topology; repair the source mesh explicitly')
        bm.from_mesh(probe)
        if (not bm.faces or not all(e.is_manifold for e in bm.edges)
                or not all(f.calc_area() > 0 for f in bm.faces)):
            return None
        pending = [next(iter(bm.faces))]
        seen = set(pending)
        while pending:
            for edge in pending.pop().edges:
                for face in edge.link_faces:
                    if face not in seen:
                        seen.add(face)
                        pending.append(face)
        if len(seen) != len(bm.faces):
            return None
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        if bm.calc_volume(signed=True) < 0:
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        if (not all(e.is_contiguous for e in bm.edges) or bm.calc_volume(signed=True) <= 0):
            return None
        bm.to_mesh(probe)
        probe.update()
        keep = True
        return probe
    finally:
        bm.free()
        if not keep:
            bpy.data.meshes.remove(probe)
