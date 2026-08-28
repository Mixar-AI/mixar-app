# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deterministic assembly measurement: mate gate + span-based connectivity.

Implements the paper's verification stack on the compiled Blender objects:

- Mate gate (Eq. 2): per static mate, the REGISTRATION AREA a(c) of the two
  bodies near the mate interface plane and the max body-into-body
  PENETRATION depth — so a part that merely hovers near its partner, or
  gouges into it, is rejected with measured numbers.
- Span-based connectivity (Eq. 3-4): union-find over parts by surface
  proximity; the body is the largest-volume component; any other component
  whose AABB span reaches FLOATER_SPAN_TAU of the model span is a VISIBLE
  floater. Volume-based checks miss thin flat panels — span does not.

All sampling is deterministic (fixed strides, no randomness).
"""

from __future__ import annotations

import math

import numpy as np
from mathutils.bvhtree import BVHTree

from . import frames, mates, spec

_MAX_SAMPLE_VERTS = 400
_GRID_N = 24


def world_verts(obj) -> np.ndarray:
    mesh = obj.data
    n = len(mesh.vertices)
    if n == 0:
        return np.zeros((0, 3), dtype=np.float64)
    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(obj.matrix_world, dtype=np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def world_bvh(obj) -> BVHTree | None:
    mesh = obj.data
    if len(mesh.polygons) == 0:
        return None
    verts = [tuple(v) for v in world_verts(obj)]
    li = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", li)
    polys = []
    for p in mesh.polygons:
        s = p.loop_start
        polys.append([int(li[s + k]) for k in range(p.loop_total)])
    return BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)


def _sample(verts: np.ndarray, cap: int = _MAX_SAMPLE_VERTS) -> np.ndarray:
    if len(verts) <= cap:
        return verts
    stride = int(math.ceil(len(verts) / cap))
    return verts[::stride]


def _signed_inside(bvh: BVHTree, pt) -> float:
    """Penetration depth of ``pt`` into the closed mesh behind ``bvh``
    (0.0 when outside). Closed-manifold normal test — CSG outputs are closed."""
    hit = bvh.find_nearest(pt)
    if hit is None or hit[0] is None:
        return 0.0
    co, normal, _idx, dist = hit
    v = (pt[0] - co[0], pt[1] - co[1], pt[2] - co[2])
    inside = (v[0] * normal[0] + v[1] * normal[1] + v[2] * normal[2]) < 0.0
    return float(dist) if inside else 0.0


def penetration(bvh_a: BVHTree, verts_b: np.ndarray,
                bvh_b: BVHTree, verts_a: np.ndarray) -> float:
    """Max body-into-body penetration between two parts, both directions."""
    worst = 0.0
    for bvh, verts in ((bvh_a, _sample(verts_b)), (bvh_b, _sample(verts_a))):
        for v in verts:
            worst = max(worst, _signed_inside(bvh, tuple(v)))
    return worst


def min_surface_distance(bvh_b: BVHTree, verts_a: np.ndarray) -> float:
    best = float("inf")
    for v in _sample(verts_a, 150):
        hit = bvh_b.find_nearest(tuple(v))
        if hit is not None and hit[0] is not None:
            best = min(best, float(hit[3]))
            if best <= 0.0:
                return 0.0
    return best


def registration_area(
    bvh_a: BVHTree, bvh_b: BVHTree, frame_world, d: float, fit: str,
) -> float:
    """Contact area (m^2) of the two bodies near the mate interface plane:
    grid cells (in frame XY, z=0) where BOTH surfaces lie within the contact
    gap. Approximate but monotone — exactly what a gate needs."""
    gap = max(0.0025, abs(mates.fit_offset_m(fit)) + 0.0015)
    half = 0.8 * d
    cell = (2.0 * half) / _GRID_N
    hits = 0
    for i in range(_GRID_N):
        x = -half + (i + 0.5) * cell
        for j in range(_GRID_N):
            y = -half + (j + 0.5) * cell
            p = frames.transform_point(frame_world, (x, y, 0.0))
            ha = bvh_a.find_nearest(p, gap * 1.001)
            if ha is None or ha[0] is None:
                continue
            hb = bvh_b.find_nearest(p, gap * 1.001)
            if hb is None or hb[0] is None:
                continue
            hits += 1
    return hits * cell * cell


def part_stats(obj) -> dict:
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        volume = abs(bm.calc_volume(signed=True))
    finally:
        bm.free()
    wv = world_verts(obj)
    if len(wv):
        lo, hi = wv.min(axis=0), wv.max(axis=0)
        aabb = [[round(float(v), 4) for v in lo], [round(float(v), 4) for v in hi]]
    else:
        aabb = [[0, 0, 0], [0, 0, 0]]
    tris = sum(max(p.loop_total - 2, 0) for p in mesh.polygons)
    return {"tris": int(tris), "aabb": aabb, "volume_m3": round(float(volume), 6)}


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def connectivity(part_objs: list, caches: dict) -> dict:
    """Union-find parts into touching components; report visible floaters
    (paper Eq. 3-4) plus deterministic snap fixes for each floater.

    ``caches``: {name: {"bvh", "verts", "volume", "aabb"}} built by the caller.
    """
    names = [o.name for o in part_objs]
    n = len(names)
    uf = _UnionFind(n)
    eps = spec.CONNECT_EPS_M
    aabbs = [np.array(caches[nm]["aabb"], dtype=np.float64) for nm in names]
    for i in range(n):
        for j in range(i + 1, n):
            # AABB prefilter with the connection epsilon as margin
            lo = np.maximum(aabbs[i][0], aabbs[j][0])
            hi = np.minimum(aabbs[i][1], aabbs[j][1])
            if np.any(lo - hi > eps * 2.0):
                continue
            d = min_surface_distance(caches[names[j]]["bvh"], caches[names[i]]["verts"])
            if d <= eps:
                uf.union(i, j)

    comps: dict[int, list[int]] = {}
    for i in range(n):
        comps.setdefault(uf.find(i), []).append(i)

    def comp_span(members: list[int]) -> float:
        lo = np.min([aabbs[m][0] for m in members], axis=0)
        hi = np.max([aabbs[m][1] for m in members], axis=0)
        return float(np.max(hi - lo))

    all_lo = np.min([b[0] for b in aabbs], axis=0)
    all_hi = np.max([b[1] for b in aabbs], axis=0)
    model_span = float(np.max(all_hi - all_lo)) or 1.0

    ranked = sorted(
        comps.values(),
        key=lambda ms: sum(caches[names[m]]["volume"] for m in ms),
        reverse=True,
    )
    body = ranked[0] if ranked else []
    floaters = []
    fixes = []
    for members in ranked[1:]:
        frac = comp_span(members) / model_span
        if frac < spec.FLOATER_SPAN_TAU:
            continue
        member_names = [names[m] for m in members]
        floaters.append({
            "parts": member_names,
            "span_frac": round(frac, 4),
        })
        fix = _snap_fix(members, body, names, caches)
        if fix:
            fixes.append(fix)
    return {
        "components": len(ranked),
        "body_parts": [names[m] for m in body],
        "visible_floaters": floaters,
        "floater_fixes": fixes,
        "model_span_m": round(model_span, 4),
    }


def _snap_fix(members: list[int], body: list[int], names, caches) -> dict | None:
    """Translation that closes the gap between a floater component and the
    body (nearest surface pair + 1 mm of overlap), for asm.nudge()."""
    if not body:
        return None
    best = None  # (dist, from_pt, to_pt, member_name)
    for m in members:
        verts = _sample(caches[names[m]]["verts"], 100)
        for b in body:
            bvh = caches[names[b]]["bvh"]
            for v in verts:
                hit = bvh.find_nearest(tuple(v))
                if hit is None or hit[0] is None:
                    continue
                dist = float(hit[3])
                if best is None or dist < best[0]:
                    best = (dist, tuple(v), tuple(hit[0]), names[m])
    if best is None or best[0] <= 0.0:
        return None
    dist, src, dst, _ = best
    direction = tuple((dst[k] - src[k]) / dist for k in range(3))
    move = dist + 0.001  # close the gap and overlap 1mm so the weld reads
    return {
        "parts": [names[m] for m in members],
        "delta": [round(direction[k] * move, 5) for k in range(3)],
        "gap_m": round(dist, 5),
    }
