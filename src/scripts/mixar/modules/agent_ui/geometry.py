# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Geometry targets and selection (spec §10 of docs/agent/ui-control.md).

Principle: the app exposes mesh elements as DATA — index, world centre,
normal, area/length, on-screen position and visibility — and the model
decides which ones to act on. Nothing here picks "the top face".

Coordinates: element centres are projected into the largest ``VIEW_3D``
area's WINDOW region and reported in WINDOW pixels (bottom-left origin), the
same space the widget dump and clicks use.

Visibility: a ray from the view origin through the element's projected point
(``scene.ray_cast`` against the evaluated depsgraph). A FACE is visible when
that ray hits THIS object on that very polygon; a VERT/EDGE when the hit
polygon contains it, or when the hit point lies within a small tolerance of
the element centre. Limitations: modifiers that change topology (subdivision,
mirror, ...) renumber the evaluated polygons, so a face may read as occluded
by its own evaluated copy — the model can toggle X-ray (Alt+Z) or disable the
modifier in the viewport. When ray casting itself is unavailable, ``visible``
is ``None`` and the reason is logged.

Generators (``*_steps``) are stepped by the pump; plain functions act
instantly. Only the bmesh/mesh SELECT flags are read here; selection state of
OBJECTS is set through bpy (selection is state, not modelling).
"""

import math

import bpy

from mixar.config.logging_config import get_logger

from . import driver as drv
from .constants import (
    ERR_INTERNAL,
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    ERR_OCCLUDED,
    GEOMETRY_ELEMENTS,
    GEOMETRY_SORTS,
    GEOMETRY_TARGETS_LIMIT_DEFAULT,
    GEOMETRY_TARGETS_LIMIT_MAX,
    SELECT_GEOMETRY_MAX,
)
from .errors import UIControlError

logger = get_logger(__name__)

# Hit point must be within this fraction of the object's largest dimension
# (plus an absolute floor) of the element centre to count as "the ray hit
# this element" when polygon indices cannot be trusted.
_HIT_TOLERANCE_REL = 0.02
_HIT_TOLERANCE_ABS = 1e-4
_MODE_WAIT_S = 2.0
_SELECT_MODE_KEYS = {"VERT": "ONE", "EDGE": "TWO", "FACE": "THREE"}


# ------------------------------------------------------------------ helpers

def _view3d_utils():
    from bpy_extras import view3d_utils
    return view3d_utils


def _context():
    return bpy.context


def _mode() -> str:
    return str(getattr(_context(), "mode", "") or "")


def _edit_object_name():
    obj = getattr(_context(), "edit_object", None)
    return getattr(obj, "name", None) if obj is not None else None


def _element(value) -> str:
    element = str(value or "").upper()
    if element not in GEOMETRY_ELEMENTS:
        raise UIControlError(ERR_INVALID_PARAMS,
                             f"element must be one of {', '.join(GEOMETRY_ELEMENTS)}")
    return element


def _resolve_object(name):
    if not isinstance(name, str) or not name:
        raise UIControlError(ERR_INVALID_PARAMS, "object must be a non-empty object name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise UIControlError(ERR_NO_MATCH, f"no object named {name!r}")
    if getattr(obj, "type", None) != "MESH":
        raise UIControlError(ERR_INVALID_PARAMS, f"{name!r} is not a mesh object")
    return obj


def _index(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise UIControlError(ERR_INVALID_PARAMS, "index must be an integer")


def view3d_region():
    """(window, area, region, rv3d) of the largest 3D viewport's WINDOW region."""
    win = drv.main_window()
    areas = [a for a in win.screen.areas if a.type == "VIEW_3D"]
    if not areas:
        raise UIControlError(ERR_NO_MATCH, "no VIEW_3D area in the main window")
    area = max(areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == "WINDOW" and r.width > 1), None)
    if region is None:
        raise UIControlError(ERR_NO_MATCH, "VIEW_3D has no WINDOW region")
    rv3d = getattr(region, "data", None)
    if rv3d is None:
        space = getattr(getattr(area, "spaces", None), "active", None)
        rv3d = getattr(space, "region_3d", None)
    if rv3d is None:
        raise UIControlError(ERR_NO_MATCH, "VIEW_3D region has no 3D view data")
    return win, area, region, rv3d


def region_to_window(region, rx, ry):
    """Region-local pixels -> window pixels (both bottom-left origin)."""
    return int(round(region.x + rx)), int(round(region.y + ry))


def project(region, rv3d, world_co):
    """World point -> window pixels, or None when behind the view or outside
    the region rect."""
    co = _view3d_utils().location_3d_to_region_2d(region, rv3d, world_co, default=None)
    if co is None:
        return None
    rx, ry = float(co[0]), float(co[1])
    if not (math.isfinite(rx) and math.isfinite(ry)):
        return None
    if not (0 <= rx < region.width and 0 <= ry < region.height):
        return None
    return region_to_window(region, rx, ry)


def _poly_area_world(coords):
    """Area of a planar polygon from its world-space vertices (shoelace in 3D)."""
    n = len(coords)
    if n < 3:
        return 0.0
    sx = sy = sz = 0.0
    for i in range(n):
        a = coords[i]
        b = coords[(i + 1) % n]
        sx += a[1] * b[2] - a[2] * b[1]
        sy += a[2] * b[0] - a[0] * b[2]
        sz += a[0] * b[1] - a[1] * b[0]
    return 0.5 * math.sqrt(sx * sx + sy * sy + sz * sz)


def _normalized(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 0.0:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _normal_matrix(mw):
    try:
        return mw.to_3x3().inverted_safe().transposed()
    except Exception:
        return mw.to_3x3()


def element_records(obj, element):
    """Every element of ``obj`` as {index, world_center, normal, area, length,
    selected, faces} (``faces`` = adjacent polygon indices for VERT/EDGE, used
    by the visibility test). Edit-mode reads go through bmesh WITHOUT any
    flush; object mode reads mesh data. World space throughout."""
    mw = obj.matrix_world
    nmat = _normal_matrix(mw)
    records = []
    if getattr(obj, "mode", "") == "EDIT":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        if element == "FACE":
            for f in bm.faces:
                coords = [tuple(mw @ v.co) for v in f.verts]
                records.append({
                    "index": f.index, "world_center": tuple(mw @ f.calc_center_median()),
                    "normal": _normalized(tuple(nmat @ f.normal)),
                    "area": _poly_area_world(coords), "length": None,
                    "selected": bool(f.select), "faces": (f.index,),
                })
        elif element == "EDGE":
            for e in bm.edges:
                a = mw @ e.verts[0].co
                b = mw @ e.verts[1].co
                records.append({
                    "index": e.index, "world_center": tuple((a + b) * 0.5),
                    "normal": _normalized(tuple(nmat @ (e.verts[0].normal + e.verts[1].normal))),
                    "area": None, "length": float((a - b).length),
                    "selected": bool(e.select),
                    "faces": tuple(f.index for f in e.link_faces),
                })
        else:
            for v in bm.verts:
                records.append({
                    "index": v.index, "world_center": tuple(mw @ v.co),
                    "normal": _normalized(tuple(nmat @ v.normal)),
                    "area": None, "length": None, "selected": bool(v.select),
                    "faces": tuple(f.index for f in v.link_faces),
                })
        return records

    mesh = obj.data
    if element == "FACE":
        for p in mesh.polygons:
            coords = [tuple(mw @ mesh.vertices[i].co) for i in p.vertices]
            records.append({
                "index": p.index, "world_center": tuple(mw @ p.center),
                "normal": _normalized(tuple(nmat @ p.normal)),
                "area": _poly_area_world(coords), "length": None,
                "selected": bool(p.select), "faces": (p.index,),
            })
        return records
    # Adjacency for verts/edges from the polygon table (one pass).
    vert_faces = {}
    edge_faces = {}
    for p in mesh.polygons:
        for vi in p.vertices:
            vert_faces.setdefault(vi, []).append(p.index)
        for ek in p.edge_keys:
            edge_faces.setdefault(ek, []).append(p.index)
    if element == "EDGE":
        for e in mesh.edges:
            i0, i1 = e.vertices[0], e.vertices[1]
            a = mw @ mesh.vertices[i0].co
            b = mw @ mesh.vertices[i1].co
            key = (i0, i1) if i0 < i1 else (i1, i0)
            records.append({
                "index": e.index, "world_center": tuple((a + b) * 0.5),
                "normal": _normalized(tuple(nmat @ (mesh.vertices[i0].normal + mesh.vertices[i1].normal))),
                "area": None, "length": float((a - b).length), "selected": bool(e.select),
                "faces": tuple(edge_faces.get(key, ())),
            })
        return records
    for v in mesh.vertices:
        records.append({
            "index": v.index, "world_center": tuple(mw @ v.co),
            "normal": _normalized(tuple(nmat @ v.normal)),
            "area": None, "length": None, "selected": bool(v.select),
            "faces": tuple(vert_faces.get(v.index, ())),
        })
    return records


def _object_tolerance(obj):
    try:
        dims = obj.dimensions
        largest = max(float(dims[0]), float(dims[1]), float(dims[2]))
    except Exception:
        largest = 1.0
    return max(_HIT_TOLERANCE_ABS, largest * _HIT_TOLERANCE_REL)


def _same_object(hit_obj, obj) -> bool:
    if hit_obj is None:
        return False
    if hit_obj is obj:
        return True
    original = getattr(hit_obj, "original", None)
    if original is not None and original is obj:
        return True
    return getattr(hit_obj, "name", None) == getattr(obj, "name", None)


def visible(scene, depsgraph, region, rv3d, obj, element, record):
    """True when a ray from the view origin through the element's projected
    point hits THIS element first; False when something else is in front;
    None when ray casting is unavailable (see module docstring)."""
    try:
        v3d = _view3d_utils()
        co = v3d.location_3d_to_region_2d(region, rv3d, record["world_center"], default=None)
        if co is None:
            return False
        origin = v3d.region_2d_to_origin_3d(region, rv3d, co)
        direction = v3d.region_2d_to_vector_3d(region, rv3d, co)
        result = scene.ray_cast(depsgraph, origin, direction)
    except Exception as exc:
        logger.debug("agent_ui geometry: ray cast unavailable: %s", exc)
        return None
    hit, location, _normal, face_index, hit_obj, _matrix = result
    if not hit or not _same_object(hit_obj, obj):
        return False
    if element == "FACE" and face_index == record["index"]:
        return True
    if element != "FACE" and face_index in record.get("faces", ()):
        return True
    center = record["world_center"]
    dist = math.sqrt(sum((float(location[i]) - float(center[i])) ** 2 for i in range(3)))
    return dist <= _object_tolerance(obj)


def _sort_key(sort, view_origin):
    axis = {"x": 0, "y": 1, "z": 2}
    if sort == "index":
        return lambda r: r["index"], False
    if sort == "area":
        return lambda r: (r["area"] if r["area"] is not None else
                          (r["length"] if r["length"] is not None else 0.0)), True
    if sort == "distance":
        if view_origin is None:
            return lambda r: r["index"], False
        return (lambda r: math.sqrt(sum((r["world_center"][i] - view_origin[i]) ** 2
                                        for i in range(3))), False)
    desc = sort.startswith("-")
    idx = axis[sort.lstrip("-")]
    return (lambda r: r["world_center"][idx]), desc


def order_targets(records, sort, view_origin=None):
    """Stable ordering per spec: area = largest first; z/x/y ascending,
    -z/-x/-y descending; distance = nearest the view origin first."""
    if sort not in GEOMETRY_SORTS:
        raise UIControlError(ERR_INVALID_PARAMS, f"sort must be one of {', '.join(GEOMETRY_SORTS)}")
    key, reverse = _sort_key(sort, view_origin)
    return sorted(records, key=key, reverse=reverse)


def filter_targets(records, visible_only=False, selected_only=False):
    out = records
    if visible_only:
        out = [r for r in out if r.get("visible") is True]
    if selected_only:
        out = [r for r in out if r.get("selected")]
    return out


def target_record(r) -> dict:
    """Wire shape of one target (spec §10)."""
    c = r["world_center"]
    n = r["normal"]
    xy = r.get("window_xy")
    return {
        "index": int(r["index"]),
        "window_xy": [int(xy[0]), int(xy[1])] if xy else None,
        "world_center": [round(float(c[0]), 4), round(float(c[1]), 4), round(float(c[2]), 4)],
        "normal": [round(float(n[0]), 4), round(float(n[1]), 4), round(float(n[2]), 4)],
        "area": (round(float(r["area"]), 5) if r.get("area") is not None else None),
        "length": (round(float(r["length"]), 5) if r.get("length") is not None else None),
        "visible": r.get("visible"),
        "selected": bool(r.get("selected")),
    }


def _view_origin(region, rv3d):
    try:
        v3d = _view3d_utils()
        o = v3d.region_2d_to_origin_3d(region, rv3d, (region.width / 2.0, region.height / 2.0))
        return (float(o[0]), float(o[1]), float(o[2]))
    except Exception:
        return None


def _annotate(records, region, rv3d, obj, element, want_visible=True):
    """Add window_xy + visible to each record in place."""
    ctx = _context()
    scene = getattr(ctx, "scene", None)
    depsgraph = None
    if want_visible:
        try:
            depsgraph = ctx.evaluated_depsgraph_get()
        except Exception as exc:
            logger.debug("agent_ui geometry: no depsgraph: %s", exc)
    for r in records:
        xy = project(region, rv3d, r["world_center"])
        r["window_xy"] = xy
        if xy is None:
            r["visible"] = False
        elif want_visible and scene is not None and depsgraph is not None:
            r["visible"] = visible(scene, depsgraph, region, rv3d, obj, element, r)
        else:
            r["visible"] = None
    return records


# ------------------------------------------------------------- read method

def geometry_targets(params) -> dict:
    obj = _resolve_object(params.get("object"))
    element = _element(params.get("element"))
    try:
        limit = int(params.get("limit", GEOMETRY_TARGETS_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        raise UIControlError(ERR_INVALID_PARAMS, "limit must be an integer")
    limit = max(1, min(GEOMETRY_TARGETS_LIMIT_MAX, limit))
    sort = str(params.get("sort") or "index")
    if sort not in GEOMETRY_SORTS:
        raise UIControlError(ERR_INVALID_PARAMS, f"sort must be one of {', '.join(GEOMETRY_SORTS)}")
    visible_only = bool(params.get("visible_only"))
    selected_only = bool(params.get("selected_only"))

    _win, area, region, rv3d = view3d_region()
    records = element_records(obj, element)
    _annotate(records, region, rv3d, obj, element)
    filtered = filter_targets(records, visible_only=visible_only, selected_only=selected_only)
    ordered = order_targets(filtered, sort, _view_origin(region, rv3d))
    targets = [target_record(r) for r in ordered[:limit]]
    return {
        "object": obj.name, "element": element, "mode": _mode(),
        "view": {
            "area_rect": [area.x, area.y, area.x + area.width, area.y + area.height],
            "region_rect": [region.x, region.y, region.x + region.width,
                            region.y + region.height],
        },
        "total": len(filtered), "returned": len(targets), "targets": targets,
    }


# ------------------------------------------------------- action generators

def _wait_steps(pred, timeout, what):
    import time
    end = time.monotonic() + timeout
    while True:
        try:
            if pred():
                return True
        except Exception:
            pass
        if time.monotonic() >= end:
            raise UIControlError(ERR_INTERNAL, f"timed out waiting for {what}")
        yield 0.1


def _select_object(obj):
    """Selection is state, not modelling: make ``obj`` the only selected,
    active object through bpy before entering edit mode."""
    ctx = _context()
    try:
        for other in ctx.view_layer.objects:
            try:
                other.select_set(other == obj or other.name == obj.name)
            except Exception:
                pass
        ctx.view_layer.objects.active = obj
    except Exception as exc:
        raise UIControlError(ERR_INTERNAL, f"could not make {obj.name!r} active: {exc}")


def ensure_edit_mode_steps(obj):
    """Enter edit mode ON ``obj`` the human way (Tab in the viewport)."""
    if _mode() == "EDIT_MESH" and _edit_object_name() == obj.name:
        return
    win = drv.main_window()
    if _mode() != "OBJECT":
        # Leave whatever mode another object is in first.
        yield from drv.focus_area_steps("VIEW_3D")
        drv.press(win, "TAB")
        yield from _wait_steps(lambda: _mode() == "OBJECT", _MODE_WAIT_S, "object mode")
    _select_object(obj)
    yield 0.05
    yield from drv.focus_area_steps("VIEW_3D")
    drv.press(win, "TAB")
    yield from _wait_steps(lambda: _mode() == "EDIT_MESH" and _edit_object_name() == obj.name,
                           _MODE_WAIT_S, f"edit mode on {obj.name!r}")


def _select_mode():
    ts = _context().scene.tool_settings.mesh_select_mode
    return (bool(ts[0]), bool(ts[1]), bool(ts[2]))


def ensure_select_mode_steps(element):
    """Press 1/2/3 with the pointer in the viewport until the mesh select
    mode is exactly vert/edge/face."""
    want = {"VERT": (True, False, False), "EDGE": (False, True, False),
            "FACE": (False, False, True)}[element]
    if _select_mode() == want:
        return
    win = drv.main_window()
    yield from drv.focus_area_steps("VIEW_3D")
    drv.press(win, _SELECT_MODE_KEYS[element])
    yield from _wait_steps(lambda: _select_mode() == want, _MODE_WAIT_S,
                           f"{element.lower()} select mode")


def select_flag(obj, element, index):
    """Live select flag of one element (bmesh in edit mode)."""
    if getattr(obj, "mode", "") == "EDIT":
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        seq = {"VERT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}[element]
        seq.ensure_lookup_table()
        if index < 0 or index >= len(seq):
            raise UIControlError(ERR_NO_MATCH, f"{element.lower()} index {index} out of range")
        return bool(seq[index].select)
    mesh = obj.data
    seq = {"VERT": mesh.vertices, "EDGE": mesh.edges, "FACE": mesh.polygons}[element]
    if index < 0 or index >= len(seq):
        raise UIControlError(ERR_NO_MATCH, f"{element.lower()} index {index} out of range")
    return bool(seq[index].select)


def _locate(obj, element, index):
    """Fresh projection + visibility of ONE element; raises no_match /
    occluded so callers never click a stale or hidden target."""
    records = element_records(obj, element)
    record = next((r for r in records if r["index"] == index), None)
    if record is None:
        raise UIControlError(ERR_NO_MATCH, f"{element.lower()} index {index} out of range")
    _win, _area, region, rv3d = view3d_region()
    _annotate([record], region, rv3d, obj, element)
    if record["window_xy"] is None:
        raise UIControlError(ERR_NO_MATCH,
                             f"{element.lower()} {index} is off-screen — orbit or frame it first")
    # With X-ray on, Blender selects through geometry (face dots / hidden
    # verts are clickable), so an occluded element is a valid target.
    space = getattr(getattr(_area, "spaces", None), "active", None)
    xray = bool(getattr(getattr(space, "shading", None), "show_xray", False))
    record["xray"] = xray
    if record["visible"] is False and not xray:
        raise UIControlError(ERR_OCCLUDED,
                             f"{element.lower()} {index} is behind other geometry — orbit the "
                             "view (NUMPAD keys) or toggle X-ray (Alt+Z), then retry")
    return record


def _click_element_steps(win, record, shift=False):
    x, y = record["window_xy"]
    yield from drv.click_xy_steps(win, x, y, shift=shift)
    yield 0.1


def click_geometry_steps(params):
    yield from drv.dismiss_foreign_popups_steps()
    obj = _resolve_object(params.get("object"))
    element = _element(params.get("element"))
    index = _index(params.get("index"))
    extend = bool(params.get("extend"))
    deselect = bool(params.get("deselect"))
    yield from ensure_edit_mode_steps(obj)
    yield from ensure_select_mode_steps(element)
    win = drv.main_window()
    yield from drv.focus_area_steps("VIEW_3D")
    record = _locate(obj, element, index)
    if deselect:
        # The default keymap has no deselect modifier: Shift+click TOGGLES
        # (first click on a selected-but-not-active element makes it active,
        # the next one deselects). Toggle until the flag reads False, twice
        # at most; already-deselected elements are left alone.
        for _ in range(2):
            if not select_flag(obj, element, index):
                break
            yield from _click_element_steps(win, record, shift=True)
    else:
        yield from _click_element_steps(win, record, shift=extend)
    selected = select_flag(obj, element, index)
    return {"index": index, "window_xy": list(record["window_xy"]),
            "selected": selected, "mode": _mode()}


def select_geometry_steps(params):
    yield from drv.dismiss_foreign_popups_steps()
    obj = _resolve_object(params.get("object"))
    element = _element(params.get("element"))
    raw = params.get("indices")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise UIControlError(ERR_INVALID_PARAMS, "indices must be a non-empty list")
    if len(raw) > SELECT_GEOMETRY_MAX:
        raise UIControlError(ERR_INVALID_PARAMS,
                             f"at most {SELECT_GEOMETRY_MAX} indices per request")
    indices = []
    for v in raw:
        i = _index(v)
        if i not in indices:
            indices.append(i)
    mode = str(params.get("mode") or "replace").lower()
    if mode not in ("replace", "extend"):
        raise UIControlError(ERR_INVALID_PARAMS, "mode must be 'replace' or 'extend'")

    yield from ensure_edit_mode_steps(obj)
    yield from ensure_select_mode_steps(element)
    win = drv.main_window()
    yield from drv.focus_area_steps("VIEW_3D")
    if mode == "replace":
        drv.press(win, "A", alt=True)  # mesh.select_all action=DESELECT
        yield 0.1

    failed = []
    for index in indices:
        try:
            if select_flag(obj, element, index):
                continue  # Shift+click would toggle it OFF; it is already in.
            record = _locate(obj, element, index)
        except UIControlError as exc:
            failed.append({"index": index, "reason": exc.code})
            continue
        yield from _click_element_steps(win, record, shift=True)

    selected = []
    for index in indices:
        try:
            if select_flag(obj, element, index):
                selected.append(index)
            elif not any(f["index"] == index for f in failed):
                failed.append({"index": index, "reason": "not_selected"})
        except UIControlError as exc:
            if not any(f["index"] == index for f in failed):
                failed.append({"index": index, "reason": exc.code})
    total = _count_selected(obj, element)
    return {"requested": indices, "selected": selected, "failed": failed,
            "count_selected_total": total}


def _count_selected(obj, element):
    try:
        if getattr(obj, "mode", "") == "EDIT":
            import bmesh
            bm = bmesh.from_edit_mesh(obj.data)
            seq = {"VERT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}[element]
            return sum(1 for e in seq if e.select)
        mesh = obj.data
        seq = {"VERT": mesh.vertices, "EDGE": mesh.edges, "FACE": mesh.polygons}[element]
        return sum(1 for e in seq if e.select)
    except Exception:
        return None
