# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real-world texture scale for agent-applied tileable materials.

A layered-material base is one seamless swatch that depicts ``tile_size_m``
metres of real surface. Sampled through a mesh's authoring UV map it repeats
once per UV unit, so its apparent size depends on how large each object's UV
islands happen to be: a 6 m floor and a 20 cm cup unwrapped to the same 0..1
square show the same number of planks, and a primitive cube scaled to a long
board stretches its grain along one axis.

This module writes a dedicated UV map in which ONE UV unit is ONE metre of the
object's surface (object scale included), so a single shared material with
``uniform_scale = 1 / tile_size_m`` repeats every ``tile_size_m`` metres on
every object that carries it. The map is filled only for the polygons of the
planned material slots and is derived from the authoring UV map by a uniform
rescale when that map is healthy (the unwrap, its seams and orientation are
kept), or by a metric box projection when it is missing, stretched or
degenerate. The authoring UV map itself — painting, baking, export — is never
modified, and the mesh's active / render UV selection is left as it was.

The math lives in plain numpy functions so it is testable without Blender.
"""

from __future__ import annotations

import math

import numpy as np

REAL_SCALE_UV_NAME = "MixarRealScaleUV"
MAX_UV_LAYERS = 8

# A healthy authoring UV map keeps its unwrap; anything worse is re-projected.
# Anisotropy: area-weighted geometric mean of the per-triangle stretch ratio
# (1.0 = square texels). A primitive cube scaled 2:1 reads 2.0.
MAX_ANISOTROPY = 1.3
# Share of the selected surface whose UV triangles collapsed to ~zero area.
MAX_DEGENERATE_FRACTION = 0.02
# p90 / p10 of the per-triangle density: islands scaled very differently from
# each other would repeat the texture at different sizes on one object.
MAX_DENSITY_SPREAD = 2.5

_EPS_AREA = 1e-12


# ---------------------------------------------------------------- pure math --


def triangle_metrics(tri_pos: np.ndarray, tri_uv: np.ndarray) -> dict:
    """Per-triangle surface area, UV area and stretch.

    Args:
        tri_pos: ``(n, 3, 3)`` metric vertex positions of each triangle.
        tri_uv: ``(n, 3, 2)`` UV coordinates of the same corners.

    Returns ``{"area": (n,), "uv_area": (n,), "anisotropy": (n,)}`` where
    anisotropy is the ratio of the singular values of the metre -> UV map of
    each triangle (``inf`` for a degenerate UV triangle).
    """
    e1 = tri_pos[:, 1] - tri_pos[:, 0]
    e2 = tri_pos[:, 2] - tri_pos[:, 0]
    cross = np.cross(e1, e2)
    double_area = np.linalg.norm(cross, axis=1)
    area = 0.5 * double_area

    d1 = tri_uv[:, 1] - tri_uv[:, 0]
    d2 = tri_uv[:, 2] - tri_uv[:, 0]
    uv_double = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    uv_area = 0.5 * np.abs(uv_double)

    # 2-D frame on each triangle's plane: x along e1, y completing the plane.
    len1 = np.linalg.norm(e1, axis=1)
    safe_len1 = np.where(len1 > 0, len1, 1.0)
    x_hat = e1 / safe_len1[:, None]
    safe_double = np.where(double_area > 0, double_area, 1.0)
    n_hat = cross / safe_double[:, None]
    y_hat = np.cross(n_hat, x_hat)
    q1x = len1
    q2x = np.einsum("ij,ij->i", e2, x_hat)
    q2y = np.einsum("ij,ij->i", e2, y_hat)

    # J = D @ inverse(Q), Q = [[q1x, q2x], [0, q2y]] (upper triangular).
    det_q = q1x * q2y
    ok = (np.abs(det_q) > _EPS_AREA) & (uv_area > _EPS_AREA)
    safe_det = np.where(ok, det_q, 1.0)
    inv00 = q2y / safe_det
    inv01 = -q2x / safe_det
    inv11 = q1x / safe_det
    j00 = d1[:, 0] * inv00
    j01 = d1[:, 0] * inv01 + d2[:, 0] * inv11
    j10 = d1[:, 1] * inv00
    j11 = d1[:, 1] * inv01 + d2[:, 1] * inv11
    frob = j00 ** 2 + j01 ** 2 + j10 ** 2 + j11 ** 2
    det_j = np.abs(j00 * j11 - j01 * j10)
    disc = np.sqrt(np.maximum(frob ** 2 - 4.0 * det_j ** 2, 0.0))
    s_max = np.sqrt(np.maximum((frob + disc) / 2.0, 0.0))
    s_min = np.sqrt(np.maximum((frob - disc) / 2.0, 0.0))
    anisotropy = np.full(area.shape, np.inf)
    good = ok & (s_min > 0)
    anisotropy[good] = s_max[good] / s_min[good]
    return {"area": area, "uv_area": uv_area, "anisotropy": anisotropy}


def summarize_uv_health(metrics: dict) -> dict:
    """Area-weighted density, stretch and degeneracy of one UV region.

    ``meters_per_uv`` is the edge length in metres that one UV unit covers on
    average (``None`` when the region has no usable UV area).
    """
    area = metrics["area"]
    uv_area = metrics["uv_area"]
    aniso = metrics["anisotropy"]
    total = float(area.sum())
    if total <= 0.0:
        return {
            "meters_per_uv": None, "anisotropy": math.inf,
            "degenerate_fraction": 1.0, "density_spread": math.inf,
            "surface_area_m2": 0.0,
        }
    usable = np.isfinite(aniso) & (area > 0)
    degenerate = float(area[~usable].sum()) / total
    uv_total = float(uv_area[usable].sum())
    if uv_total <= _EPS_AREA or not usable.any():
        return {
            "meters_per_uv": None, "anisotropy": math.inf,
            "degenerate_fraction": degenerate, "density_spread": math.inf,
            "surface_area_m2": total,
        }
    weights = area[usable]
    mean_log_aniso = float(np.average(np.log(aniso[usable]), weights=weights))
    density = np.sqrt(area[usable] / uv_area[usable])
    spread = _weighted_quantile(density, weights, 0.9) / max(
        _weighted_quantile(density, weights, 0.1), 1e-12
    )
    return {
        "meters_per_uv": math.sqrt(float(area[usable].sum()) / uv_total),
        "anisotropy": math.exp(mean_log_aniso),
        "degenerate_fraction": degenerate,
        "density_spread": float(spread),
        "surface_area_m2": total,
    }


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    cutoff = q * cumulative[-1]
    return float(values[order][min(np.searchsorted(cumulative, cutoff), len(order) - 1)])


def uv_is_reusable(health: dict) -> bool:
    """True when an authoring UV map can be rescaled into metres as-is."""
    return (
        health.get("meters_per_uv") is not None
        and health["anisotropy"] <= MAX_ANISOTROPY
        and health["degenerate_fraction"] <= MAX_DEGENERATE_FRACTION
        and health["density_spread"] <= MAX_DENSITY_SPREAD
    )


def _levi_civita(a: int, b: int, c: int) -> int:
    return 1 if (a, b, c) in ((0, 1, 2), (1, 2, 0), (2, 0, 1)) else -1


def box_projection_axes(extents) -> dict:
    """Per dominant axis ``d``: ``(u_axis, v_axis, handedness)``.

    V follows the longest in-plane axis of the object so directional finishes
    (grain, planks, brushing) run along boards and panels consistently, and U
    is signed so no face shows a mirrored texture from outside.
    """
    order = [int(a) for a in np.argsort(-np.asarray(extents, dtype=float), kind="stable")]
    axes = {}
    for d in range(3):
        others = [a for a in order if a != d]
        v_axis, u_axis = others[0], others[1]
        axes[d] = (u_axis, v_axis, _levi_civita(u_axis, v_axis, d))
    return axes


def box_project(loop_pos: np.ndarray, loop_normal: np.ndarray, extents) -> np.ndarray:
    """Metric box projection: one UV unit per metre, per-face dominant axis.

    Args:
        loop_pos: ``(n, 3)`` metric position of each loop's vertex.
        loop_normal: ``(n, 3)`` metric normal of each loop's polygon.
        extents: metric bounding-box size of the object (axis roles).
    """
    dominant = np.argmax(np.abs(loop_normal), axis=1)
    out = np.zeros((loop_pos.shape[0], 2), dtype=np.float64)
    for d, (u_axis, v_axis, handed) in box_projection_axes(extents).items():
        rows = dominant == d
        if not rows.any():
            continue
        sign = np.where(loop_normal[rows, d] >= 0.0, 1.0, -1.0) * handed
        out[rows, 0] = sign * loop_pos[rows, u_axis]
        out[rows, 1] = loop_pos[rows, v_axis]
    return out


# ------------------------------------------------------------ bpy accessors --


def _foreach(collection, attr: str, count: int, width: int, dtype) -> np.ndarray:
    arr = np.empty(count * width, dtype=dtype)
    collection.foreach_get(attr, arr)
    return arr.reshape(count, width) if width > 1 else arr


def _uv_vectors(uv_layer, n_loops: int) -> np.ndarray:
    try:
        return _foreach(uv_layer.uv, "vector", n_loops, 2, np.float32).astype(np.float64)
    except Exception:  # older API surface without the attribute accessor
        return _foreach(uv_layer.data, "uv", n_loops, 2, np.float32).astype(np.float64)


def _set_uv_vectors(uv_layer, values: np.ndarray) -> None:
    flat = np.ascontiguousarray(values, dtype=np.float32).ravel()
    try:
        uv_layer.uv.foreach_set("vector", flat)
    except Exception:
        uv_layer.data.foreach_set("uv", flat)


def object_metric_scale(obj) -> np.ndarray:
    """Absolute world scale of ``obj`` per local axis (parents included)."""
    try:
        scale = obj.matrix_world.to_scale()
        values = np.abs(np.array([scale[0], scale[1], scale[2]], dtype=np.float64))
    except Exception:
        values = np.ones(3)
    return np.where(values > 1e-9, values, 1.0)


def source_uv_layer(mesh):
    """The authoring UV map: the active one unless it is the metric map."""
    layers = list(getattr(mesh, "uv_layers", []) or [])
    active = getattr(mesh.uv_layers, "active", None) if layers else None
    if active is not None and active.name != REAL_SCALE_UV_NAME:
        return active
    return next((layer for layer in layers if layer.name != REAL_SCALE_UV_NAME), None)


def _selected_polygons(mesh, n_poly: int, material_indices, slot_count: int) -> np.ndarray:
    if material_indices is None or slot_count == 0:
        return np.ones(n_poly, dtype=bool)
    poly_mat = _foreach(mesh.polygons, "material_index", n_poly, 1, np.int32)
    # Blender renders an out-of-range index with the LAST slot.
    poly_mat = np.clip(poly_mat, 0, max(slot_count - 1, 0))
    return np.isin(poly_mat, np.asarray(sorted(set(material_indices)), dtype=np.int32))


def measure_uv_health(obj, material_indices=None, uv_layer=None) -> dict:
    """Density / stretch report of ``obj``'s authoring UV on the planned slots."""
    mesh = obj.data
    n_poly = len(mesh.polygons)
    layer = uv_layer if uv_layer is not None else source_uv_layer(mesh)
    if layer is None or n_poly == 0:
        return {"meters_per_uv": None, "anisotropy": math.inf,
                "degenerate_fraction": 1.0, "density_spread": math.inf,
                "surface_area_m2": 0.0, "source_uv": None}
    data = _mesh_triangles(obj, material_indices)
    if data is None:
        return {"meters_per_uv": None, "anisotropy": math.inf,
                "degenerate_fraction": 1.0, "density_spread": math.inf,
                "surface_area_m2": 0.0, "source_uv": layer.name}
    uv = _uv_vectors(layer, data["n_loops"])
    tri_loops = data["tri_loops"]
    health = summarize_uv_health(
        triangle_metrics(data["pos"][data["loop_vert"][tri_loops]], uv[tri_loops])
    )
    health["source_uv"] = layer.name
    return health


def _mesh_triangles(obj, material_indices):
    mesh = obj.data
    n_vert, n_loop, n_poly = len(mesh.vertices), len(mesh.loops), len(mesh.polygons)
    if not (n_vert and n_loop and n_poly):
        return None
    scale = object_metric_scale(obj)
    pos = _foreach(mesh.vertices, "co", n_vert, 3, np.float32).astype(np.float64) * scale
    loop_vert = _foreach(mesh.loops, "vertex_index", n_loop, 1, np.int64)
    mesh.calc_loop_triangles()
    n_tri = len(mesh.loop_triangles)
    if n_tri == 0:
        return None
    tri_loops = _foreach(mesh.loop_triangles, "loops", n_tri, 3, np.int64)
    tri_poly = _foreach(mesh.loop_triangles, "polygon_index", n_tri, 1, np.int64)
    slot_count = len(getattr(obj, "material_slots", ()) or ())
    selected = _selected_polygons(mesh, n_poly, material_indices, slot_count)
    keep = selected[tri_poly]
    return {
        "scale": scale, "pos": pos, "loop_vert": loop_vert,
        "tri_loops": tri_loops[keep], "selected": selected,
        "n_loops": n_loop, "n_poly": n_poly,
    }


def _loop_polygon_index(mesh, n_poly: int, n_loop: int) -> np.ndarray:
    starts = _foreach(mesh.polygons, "loop_start", n_poly, 1, np.int64)
    totals = _foreach(mesh.polygons, "loop_total", n_poly, 1, np.int64)
    out = np.empty(n_loop, dtype=np.int64)
    if np.array_equal(starts, np.concatenate(([0], np.cumsum(totals)[:-1]))):
        out[:] = np.repeat(np.arange(n_poly, dtype=np.int64), totals)
        return out
    for index, (start, total) in enumerate(zip(starts, totals)):
        out[start:start + total] = index
    return out


def ensure_real_scale_uv(obj, material_indices=None) -> dict:
    """Write the metric UV map for ``obj``'s planned slots.

    ``material_indices`` limits the polygons written (``None`` = all). Loops of
    other polygons keep their current values, so finishes on different slots
    of one mesh each own their region of the map. Idempotent: the map is
    always recomputed from the authoring UV, never from itself.
    """
    mesh = getattr(obj, "data", None)
    if mesh is None or getattr(obj, "type", "") != "MESH":
        return {"mode": "unavailable", "reason": "not a mesh"}
    data = _mesh_triangles(obj, material_indices)
    if data is None or not data["selected"].any():
        return {"mode": "unavailable", "reason": "no polygons in the planned slots"}

    uv_layers = mesh.uv_layers
    metric = uv_layers.get(REAL_SCALE_UV_NAME)
    source = source_uv_layer(mesh)
    created = False
    if metric is None:
        if len(uv_layers) >= MAX_UV_LAYERS:
            return {"mode": "unavailable", "reason": "mesh already has the maximum UV maps"}
        active_index = uv_layers.active_index if len(uv_layers) else -1
        render_name = next((l.name for l in uv_layers if l.active_render), "")
        metric = uv_layers.new(name=REAL_SCALE_UV_NAME, do_init=bool(len(uv_layers)))
        created = True
        # Adding a layer must not change what the artist paints or renders.
        if active_index >= 0:
            uv_layers.active_index = active_index
        for layer in uv_layers:
            if layer.name == render_name:
                layer.active_render = True
        metric = uv_layers.get(REAL_SCALE_UV_NAME)
        source = source_uv_layer(mesh)

    n_loop = data["n_loops"]
    loop_poly = _loop_polygon_index(mesh, data["n_poly"], n_loop)
    loop_sel = data["selected"][loop_poly]
    values = _uv_vectors(metric, n_loop)

    health = None
    if source is not None:
        uv = _uv_vectors(source, n_loop)
        tri_loops = data["tri_loops"]
        health = summarize_uv_health(
            triangle_metrics(data["pos"][data["loop_vert"][tri_loops]], uv[tri_loops])
        )
    if health is not None and uv_is_reusable(health):
        values[loop_sel] = uv[loop_sel] * health["meters_per_uv"]
        mode = "rescaled"
    else:
        normals = _foreach(mesh.polygons, "normal", data["n_poly"], 3, np.float32)
        normals = normals.astype(np.float64) / data["scale"]
        loop_pos = data["pos"][data["loop_vert"]]
        extents = np.ptp(data["pos"], axis=0) if len(data["pos"]) else np.ones(3)
        projected = box_project(loop_pos[loop_sel], normals[loop_poly[loop_sel]], extents)
        values[loop_sel] = projected
        mode = "box_projected"
    _set_uv_vectors(metric, values)
    try:
        mesh.update()
    except Exception:
        pass

    report = {
        "uv_name": REAL_SCALE_UV_NAME,
        "mode": mode,
        "created": created,
        "source_uv": getattr(source, "name", None),
        "polygons": int(data["selected"].sum()),
    }
    if health is not None:
        report["source_meters_per_uv"] = _rounded(health["meters_per_uv"])
        report["source_anisotropy"] = _rounded(health["anisotropy"])
    return report


def _rounded(value, digits: int = 4):
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


# ------------------------------------------------ authoring UV bootstrapping --

_GRID_COLUMNS, _GRID_ROWS = 3, 2
_GRID_MARGIN = 0.01


def pack_box_groups(loop_uv: np.ndarray, loop_group: np.ndarray) -> np.ndarray:
    """Pack six box-projection groups into a 3 x 2 grid inside 0..1.

    Every group keeps ONE common scale (square texels, one density for the
    whole mesh) and gets its own cell, so opposite faces no longer overlap —
    the map is usable for painting and for baking geometry masks.
    """
    cell_w = 1.0 / _GRID_COLUMNS - 2 * _GRID_MARGIN
    cell_h = 1.0 / _GRID_ROWS - 2 * _GRID_MARGIN
    spans = []
    lows = {}
    for group in range(6):
        rows = loop_group == group
        if not rows.any():
            continue
        low = loop_uv[rows].min(axis=0)
        high = loop_uv[rows].max(axis=0)
        lows[group] = low
        spans.append(np.maximum(high - low, 1e-9))
    if not spans:
        return np.zeros_like(loop_uv)
    spans = np.array(spans)
    scale = min(cell_w / float(spans[:, 0].max()), cell_h / float(spans[:, 1].max()))
    out = np.zeros_like(loop_uv)
    for group, low in lows.items():
        rows = loop_group == group
        col, row = group % _GRID_COLUMNS, group // _GRID_COLUMNS
        origin = np.array([
            col / _GRID_COLUMNS + _GRID_MARGIN,
            row / _GRID_ROWS + _GRID_MARGIN,
        ])
        out[rows] = (loop_uv[rows] - low) * scale + origin
    return out


def create_authoring_uv(obj, name: str = "UVMap") -> bool:
    """Give a UV-less mesh a square-texel, non-overlapping box UV map.

    Faces are grouped by the signed axis their (object-scale corrected)
    normal points along, box-projected like the metric map and packed into
    their own grid cell at one common scale. Returns True when a map was made.
    """
    mesh = getattr(obj, "data", None)
    if mesh is None or getattr(obj, "type", "") != "MESH":
        return False
    if len(getattr(mesh, "uv_layers", []) or []) > 0:
        return False
    n_vert, n_loop, n_poly = len(mesh.vertices), len(mesh.loops), len(mesh.polygons)
    if not (n_vert and n_loop and n_poly):
        return False
    scale = object_metric_scale(obj)
    pos = _foreach(mesh.vertices, "co", n_vert, 3, np.float32).astype(np.float64) * scale
    loop_vert = _foreach(mesh.loops, "vertex_index", n_loop, 1, np.int64)
    loop_poly = _loop_polygon_index(mesh, n_poly, n_loop)
    normals = _foreach(mesh.polygons, "normal", n_poly, 3, np.float32).astype(np.float64) / scale
    loop_normal = normals[loop_poly]
    loop_pos = pos[loop_vert]
    projected = box_project(loop_pos, loop_normal, np.ptp(pos, axis=0))
    dominant = np.argmax(np.abs(loop_normal), axis=1)
    negative = loop_normal[np.arange(n_loop), dominant] < 0
    groups = dominant * 2 + negative.astype(np.int64)
    layer = mesh.uv_layers.new(name=name)
    _set_uv_vectors(layer, pack_box_groups(projected, groups))
    try:
        mesh.update()
    except Exception:
        pass
    return True
