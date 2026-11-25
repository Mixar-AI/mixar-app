# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Where the flake and clear coat maps of an AxF car paint lie on the surface.

The importer places them by a box projection of object-space position (metres), which is
exact on flat panels but seams and stretches on curved bodies. A UV map instead carries
them along the surface: the coordinates are the UVs times the object's average metres per
UV unit (world area over UV area, so the flakes keep their measured size), and the tangent
is the UV map's own +U direction, which the coat normal map needs.

`metres_per_uv` is pure numpy; `set_mapping` rewires a material's node tree.
"""

import numpy as np

from mixar.modules.axf import constants as C

MAPPING_BOX = "BOX"
MAPPING_UV = "UV"
PROP_MAPPING = "axf_mapping"
PROP_UV_MAP = "axf_uv_map"
PROP_UV_METRES = "axf_uv_metres"

_UV_NODE = "AxF UV Map"
_SCALE_NODE = "AxF UV Metres"
_TANGENT_NODE = "AxF UV Tangent"


def metres_per_uv(world_tris: np.ndarray, uv_tris: np.ndarray) -> float:
    """Average metres per UV unit: sqrt(world area / UV area) over all triangles.

    world_tris: (n, 3, 3) world-space corners; uv_tris: (n, 3, 2). Returns 0 when the UV
    map has no area (nothing to scale by)."""
    w = np.asarray(world_tris, np.float64)
    u = np.asarray(uv_tris, np.float64)
    if w.size == 0:
        return 0.0
    area_w = 0.5 * np.linalg.norm(np.cross(w[:, 1] - w[:, 0], w[:, 2] - w[:, 0]), axis=1).sum()
    e1, e2 = u[:, 1] - u[:, 0], u[:, 2] - u[:, 0]
    area_uv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum()
    if area_uv <= 1e-20:
        return 0.0
    return float(np.sqrt(area_w / area_uv))


def uv_aspect(world_tris: np.ndarray, uv_tris: np.ndarray) -> float:
    """Average ratio of metres per unit U to metres per unit V (1 for an undistorted
    unwrap): area-weighted lengths of the surface derivatives dP/du and dP/dv."""
    w = np.asarray(world_tris, np.float64)
    u = np.asarray(uv_tris, np.float64)
    if w.size == 0:
        return 1.0
    e = np.stack([w[:, 1] - w[:, 0], w[:, 2] - w[:, 0]], -1)          # (n, 3, 2)
    d = np.stack([u[:, 1] - u[:, 0], u[:, 2] - u[:, 0]], -1)          # (n, 2, 2)
    det = d[:, 0, 0] * d[:, 1, 1] - d[:, 0, 1] * d[:, 1, 0]
    ok = np.abs(det) > 1e-20
    if not ok.any():
        return 1.0
    inv = np.stack([np.stack([d[:, 1, 1], -d[:, 0, 1]], -1),
                    np.stack([-d[:, 1, 0], d[:, 0, 0]], -1)], -2) / np.where(ok, det, 1.0)[:, None, None]
    jac = e @ inv                                                       # (n, 3, 2): dP/du, dP/dv
    area = 0.5 * np.linalg.norm(np.cross(e[..., 0], e[..., 1]), axis=1)
    weight = np.where(ok, area, 0.0)
    su = (np.linalg.norm(jac[..., 0], axis=1) * weight).sum()
    sv = (np.linalg.norm(jac[..., 1], axis=1) * weight).sum()
    return float(su / sv) if sv > 0 and su > 0 else 1.0


def representative_triangles(world_tris: np.ndarray, uv_tris: np.ndarray,
                             spread: float = 4.0):
    """Drop triangles whose own metres-per-UV is more than spread x off the area-weighted
    median: near-degenerate UV triangles (a sliver collapsed in UV, an unwrap seam) carry
    huge surface-per-UV lengths that would otherwise dominate the aspect and inflate the
    area scale. Returns the kept (world_tris, uv_tris)."""
    w = np.asarray(world_tris, np.float64)
    u = np.asarray(uv_tris, np.float64)
    if w.size == 0:
        return w, u
    area_w = 0.5 * np.linalg.norm(np.cross(w[:, 1] - w[:, 0], w[:, 2] - w[:, 0]), axis=1)
    e1, e2 = u[:, 1] - u[:, 0], u[:, 2] - u[:, 0]
    area_uv = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    ok = (area_uv > 1e-20) & (area_w > 0.0)
    if not ok.any():
        return w[:0], u[:0]
    dens = np.sqrt(area_w[ok] / area_uv[ok])
    order = np.argsort(dens)
    cum = np.cumsum(area_w[ok][order])
    median = dens[order][np.searchsorted(cum, 0.5 * cum[-1])]
    keep = np.zeros(len(w), bool)
    keep[np.flatnonzero(ok)] = (dens >= median / spread) & (dens <= median * spread)
    return w[keep], u[keep]


def uv_scale(world_tris: np.ndarray, uv_tris: np.ndarray) -> tuple[float, float]:
    """Metres per unit U and per unit V: the area-preserving magnitude of metres_per_uv
    split by uv_aspect, so a stretched unwrap does not stretch the flakes. Both are
    measured over representative_triangles."""
    world_tris, uv_tris = representative_triangles(world_tris, uv_tris)
    s = metres_per_uv(world_tris, uv_tris)
    if s <= 0.0:
        return 0.0, 0.0
    a = np.sqrt(uv_aspect(world_tris, uv_tris))
    return float(s * a), float(s / a)


def uv_quality(world_tris: np.ndarray, uv_tris: np.ndarray) -> dict:
    """How well a UV map can carry flakes: the share of surface area whose texel density
    is within 25 % of the area-weighted median, and the median local stretch
    (max(|dP/du| / |dP/dv|, inverse) per triangle, area-weighted)."""
    w = np.asarray(world_tris, np.float64)
    u = np.asarray(uv_tris, np.float64)
    out = {'even_area': 0.0, 'stretch': float('inf'), 'triangles': int(len(w))}
    if w.size == 0:
        return out
    e = np.stack([w[:, 1] - w[:, 0], w[:, 2] - w[:, 0]], -1)
    d = np.stack([u[:, 1] - u[:, 0], u[:, 2] - u[:, 0]], -1)
    area_w = 0.5 * np.linalg.norm(np.cross(e[..., 0], e[..., 1]), axis=1)
    det = d[:, 0, 0] * d[:, 1, 1] - d[:, 0, 1] * d[:, 1, 0]
    ok = (np.abs(det) > 1e-20) & (area_w > 0.0)
    total = area_w.sum()
    if not ok.any() or total <= 0.0:
        return out
    a = area_w[ok]
    dens = np.sqrt(a / (0.5 * np.abs(det[ok])))
    order = np.argsort(dens)
    cum = np.cumsum(a[order])
    median = dens[order][np.searchsorted(cum, 0.5 * cum[-1])]
    out['even_area'] = float(a[np.abs(dens / median - 1.0) <= 0.25].sum() / total)
    inv = np.stack([np.stack([d[ok][:, 1, 1], -d[ok][:, 0, 1]], -1),
                    np.stack([-d[ok][:, 1, 0], d[ok][:, 0, 0]], -1)], -2) / det[ok][:, None, None]
    jac = e[ok] @ inv
    su, sv = np.linalg.norm(jac[..., 0], axis=1), np.linalg.norm(jac[..., 1], axis=1)
    stretch = np.maximum(su / sv, sv / su)
    order = np.argsort(stretch)
    cum = np.cumsum(a[order])
    out['stretch'] = float(stretch[order][np.searchsorted(cum, 0.5 * cum[-1])])
    return out


# A UV map is clean enough to carry the flakes when most of the surface shares one texel
# density and the unwrap is not visibly stretched.
CLEAN_EVEN_AREA = 0.8
CLEAN_STRETCH = 1.2

REASON_NO_MESH = "no_mesh"
REASON_NO_UV = "no_uv"
REASON_UNEVEN = "uneven"
REASON_STRETCHED = "stretched"


def uv_verdict(quality: dict) -> str:
    """'' when the UV map is clean, else REASON_UNEVEN / REASON_STRETCHED."""
    if quality['even_area'] < CLEAN_EVEN_AREA:
        return REASON_UNEVEN
    if quality['stretch'] > CLEAN_STRETCH:
        return REASON_STRETCHED
    return ''


def auto_uv_mapping(mat, obj, depsgraph) -> tuple[str, tuple[float, float], str]:
    """At import: place mat's flakes along obj's active render UV map when it is clean.
    Returns (reason, (metres per U, per V), uv name); an empty reason means applied."""
    if obj is None or obj.type != 'MESH':
        return REASON_NO_MESH, (0.0, 0.0), ''
    uv = next((u for u in obj.data.uv_layers if u.active_render), None)
    if uv is None:
        return REASON_NO_UV, (0.0, 0.0), ''
    tris = _object_triangles(obj, depsgraph, uv.name)
    if tris is None:
        return REASON_NO_UV, (0.0, 0.0), uv.name
    reason = uv_verdict(uv_quality(*tris))
    if reason:
        return reason, (0.0, 0.0), uv.name
    su, sv = uv_scale(*tris)
    if su <= 0.0 or sv <= 0.0:
        return REASON_UNEVEN, (0.0, 0.0), uv.name
    set_mapping(mat, MAPPING_UV, uv_name=uv.name, metres=(su, sv))
    return '', (su, sv), uv.name


def object_uv_scale(obj, depsgraph, uv_name: str) -> tuple[float, float]:
    """uv_scale of the evaluated mesh of obj, in world space, for one UV map."""
    tris = _object_triangles(obj, depsgraph, uv_name)
    return (0.0, 0.0) if tris is None else uv_scale(*tris)


def object_metres_per_uv(obj, depsgraph, uv_name: str) -> float:
    """metres_per_uv of the evaluated mesh of obj, in world space, for one UV map."""
    tris = _object_triangles(obj, depsgraph, uv_name)
    return 0.0 if tris is None else metres_per_uv(*tris)


def _object_triangles(obj, depsgraph, uv_name: str):
    """(world corners (n, 3, 3), UV corners (n, 3, 2)) of the evaluated mesh, or None."""
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        uv = mesh.uv_layers.get(uv_name)
        if uv is None:
            return None
        mesh.calc_loop_triangles()
        n = len(mesh.loop_triangles)
        if n == 0:
            return None
        tri_loops = np.empty(n * 3, np.int32)
        mesh.loop_triangles.foreach_get("loops", tri_loops)
        tri_verts = np.empty(n * 3, np.int32)
        mesh.loop_triangles.foreach_get("vertices", tri_verts)
        co = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        mw = np.array(eval_obj.matrix_world, np.float64)
        world = co @ mw[:3, :3].T + mw[:3, 3]
        uvs = np.empty(len(uv.uv) * 2, np.float32)
        uv.uv.foreach_get("vector", uvs)
        uvs = uvs.reshape(-1, 2)
        return world[tri_verts].reshape(n, 3, 3), uvs[tri_loops].reshape(n, 3, 2)
    finally:
        eval_obj.to_mesh_clear()


def car_paint_nodes(mat) -> list:
    if mat is None or mat.node_tree is None:
        return []
    return [n for n in mat.node_tree.nodes if n.bl_idname == C.NODE_IDNAME]


def _coordinate_targets(node):
    """Sockets the surface coordinates (metres) feed: the first input of each scale node
    that turns metres into flake / coat tile units, plus the node's Tangent input when the
    coat normal map uses it."""
    targets = []
    for name in ("Flake UV", "Coat UV"):
        sock = node.inputs[name]
        if sock.is_linked:
            scale = sock.links[0].from_node
            if scale.bl_idname == "ShaderNodeVectorMath":
                targets.append(scale.inputs[0])
    tangent = node.inputs["Tangent"] if node.inputs["Tangent"].is_linked or \
        node.inputs["Coat UV"].is_linked else None
    return targets, tangent


def has_mapping(mat) -> bool:
    return any(_coordinate_targets(n)[0] for n in car_paint_nodes(mat))


def _remove_upstream(nt, sockets):
    """Remove every node that only feeds the given sockets (the old coordinate graph)."""
    keep_inputs = {s.as_pointer() for s in sockets}
    stack = [l.from_node for s in sockets for l in s.links]
    seen = {}
    while stack:
        n = stack.pop()
        if n.as_pointer() in seen:
            continue
        seen[n.as_pointer()] = n
        stack.extend(l.from_node for s in n.inputs for l in s.links)
    doomed = set(seen)
    changed = True
    while changed:  # Keep any node that also feeds something outside the old graph.
        changed = False
        for ptr in list(doomed):
            n = seen[ptr]
            for out in n.outputs:
                for l in out.links:
                    if l.to_node.as_pointer() not in doomed and l.to_socket.as_pointer() not in keep_inputs:
                        doomed.discard(ptr)
                        changed = True
                        break
                if ptr not in doomed:
                    break
    for ptr in doomed:
        nt.nodes.remove(seen[ptr])


def set_mapping(mat, mapping: str, *, uv_name: str = "", metres=(0.0, 0.0)) -> int:
    """Place the flake and coat maps of every car paint node in mat by mapping
    (MAPPING_BOX or MAPPING_UV; metres = metres per unit U and per unit V). Returns how
    many nodes were rewired."""
    from mixar.modules.axf.core.blender_import import _surface_mapping

    nt = mat.node_tree
    done = 0
    for node in car_paint_nodes(mat):
        targets, tangent_in = _coordinate_targets(node)
        if not targets:
            continue
        _remove_upstream(nt, targets + ([tangent_in] if tangent_in is not None else []))
        x, y = node.location.x - 1200, node.location.y
        if mapping == MAPPING_UV:
            uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.name = uvn.label = _UV_NODE
            uvn.uv_map = uv_name; uvn.location = (x, y)
            scale = nt.nodes.new("ShaderNodeVectorMath"); scale.name = scale.label = _SCALE_NODE
            scale.operation = 'MULTIPLY'
            scale.inputs[1].default_value = (float(metres[0]), float(metres[1]), 0.0)
            scale.location = (x + 200, y)
            nt.links.new(uvn.outputs[0], scale.inputs[0])
            coords = scale.outputs[0]
            tangent = None
            if tangent_in is not None:
                tn = nt.nodes.new("ShaderNodeTangent"); tn.name = tn.label = _TANGENT_NODE
                tn.direction_type = 'UV_MAP'; tn.uv_map = uv_name; tn.location = (x + 200, y - 200)
                tangent = tn.outputs[0]
        else:
            coords, tangent = _surface_mapping(nt, x, y, tangent=tangent_in is not None)
        for sock in targets:
            nt.links.new(coords, sock)
        if tangent_in is not None:
            nt.links.new(tangent, tangent_in)
        done += 1
    if done:
        mat[PROP_MAPPING] = mapping
        if mapping == MAPPING_UV:
            mat[PROP_UV_MAP] = uv_name
            mat[PROP_UV_METRES] = [float(metres[0]), float(metres[1])]
        else:
            for key in (PROP_UV_MAP, PROP_UV_METRES):
                if key in mat:
                    del mat[key]
    return done
