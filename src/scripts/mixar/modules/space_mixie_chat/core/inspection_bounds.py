# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry-only inspection framing and focus helpers (no render jobs)."""
import bpy
from mathutils import Vector


def _corners(obj, instances=None):
    if instances and obj in instances:
        return instances[obj]
    return [obj.matrix_world @ Vector(c) for c in obj.bound_box]


def _instance_corners(context, scene):
    """One evaluated pass; keep only eight world-space corners per instancer."""
    owners = {o for o in scene.objects if o.instance_type == 'COLLECTION' and o.visible_get()}
    if not owners:
        return {}
    boxes = {}
    for item in context.evaluated_depsgraph_get().object_instances:
        if not item.is_instance or item.parent is None or not item.show_self:
            continue
        owner = item.parent.original
        if owner not in owners or item.object.type in {'EMPTY', 'CAMERA', 'LIGHT'}:
            continue
        points = [item.matrix_world @ Vector(c) for c in item.object.bound_box]
        lo, hi = boxes.setdefault(owner, (points[0].copy(), points[0].copy()))
        for p in points:
            for axis in range(3):
                lo[axis] = min(lo[axis], p[axis])
                hi[axis] = max(hi[axis], p[axis])
    return {o: [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y)
                for z in (lo.z, hi.z)] for o, (lo, hi) in boxes.items()}


def _world_aabb(objs, instances=None):
    """(min corner, max corner) of the objects' world-space bounding boxes."""
    pts = [p for o in objs for p in _corners(o, instances)]
    if not pts:
        return None
    return (
        Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
        Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))),
    )


def _boxes_touch(a, b, eps):
    """True when two world AABBs intersect or come within `eps` on every axis."""
    (a_lo, a_hi), (b_lo, b_hi) = a, b
    for i in range(3):
        if a_lo[i] - eps > b_hi[i] or b_lo[i] - eps > a_hi[i]:
            return False
    return True


def _resolve_focus(content, names, include_touching, eps, instances=None):
    """(focus objects, touching objects, missing names) for a focused capture.

    A named object contributes itself and its whole child hierarchy, so naming a
    group's root frames the group. `touching` is ONE hop out from the focus set:
    every other renderable object whose world AABB intersects or comes within
    `eps` of any focus object's. That hop is what puts the ground a build stands
    on (or should stand on) in the picture next to it."""
    visible = set(content)
    focus, missing = [], []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            missing.append(name)
            continue
        members = [m for m in [obj] + list(obj.children_recursive) if m in visible]
        if not members:
            missing.append(name)
            continue
        for member in members:
            if member not in focus:
                focus.append(member)
    if not focus or not include_touching:
        return focus, [], missing
    focus_boxes = [b for b in (_world_aabb([o], instances) for o in focus) if b is not None]
    chosen = set(focus)
    touching = []
    for obj in content:
        if obj in chosen:
            continue
        box = _world_aabb([obj], instances)
        if box is None:
            continue
        for other in focus_boxes:
            if _boxes_touch(box, other, eps):
                touching.append(obj)
                break
    return focus, touching, missing


def _z_ranges(objs, instances=None):
    """[{name, min_z, max_z}] per object — the numeric read of a support gap."""
    out = []
    for obj in objs:
        box = _world_aabb([obj], instances)
        if box is not None:
            out.append({"name": obj.name, "min_z": round(box[0].z, 4), "max_z": round(box[1].z, 4)})
    return out


def _bounds_dict(box):
    if box is None:
        return None
    lo, hi = box
    return {"min": [round(v, 4) for v in lo], "max": [round(v, 4) for v in hi]}


def _find_enclosing_shells(meshes):
    """Root groups that ENCLOSE the scene (a room shell): hiding them for the
    capture is what lets the verifier see an interior at all — from outside, the
    walls occlude every piece of furniture and the VLM honestly reports an empty
    grey box (ISSUE-006).

    A root group is a shell iff:
      1. its AABB contains most (>=60%, >=2) of the OTHER roots' centers;
      2. it is tall (dz >= 50% of scene dz) — keeps flat ground planes visible;
      3. it is HOLLOW: >=70% of its sampled verts lie near its own AABB boundary
         (walls/floor/ceiling live ON the box faces; a terrain heightfield or a
         solid prop fills the middle and fails this).
    Returns the mesh objects to hide (all meshes of each shell group)."""
    roots = {}
    for o in meshes:
        r = o
        while r.parent is not None:
            r = r.parent
        roots.setdefault(r.name, []).append(o)
    if len(roots) < 3:
        return []

    boxes = {n: _world_aabb(objs) for n, objs in roots.items()}
    roots = {n: objs for n, objs in roots.items() if boxes.get(n) is not None}
    boxes = {n: boxes[n] for n in roots}
    if not boxes:
        return []
    scene_dz = max(b[1].z for b in boxes.values()) - min(b[0].z for b in boxes.values())
    shells = []
    for name, objs in roots.items():
        lo, hi = boxes[name]
        if scene_dz > 0 and (hi.z - lo.z) < 0.5 * scene_dz:
            continue
        others = [(boxes[n][0] + boxes[n][1]) / 2 for n in roots if n != name]
        margin = 0.02 * max(hi.x - lo.x, hi.y - lo.y, 1e-6)
        inside = [
            c for c in others
            if lo.x - margin <= c.x <= hi.x + margin
            and lo.y - margin <= c.y <= hi.y + margin
            and lo.z - margin <= c.z <= hi.z + margin
        ]
        if len(inside) < 2 or len(inside) < 0.6 * len(others):
            continue
        eps = 0.03 * max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z, 1e-6)
        near = 0
        total = 0
        for o in objs:
            vs = o.data.vertices
            if not vs:
                continue
            step = max(1, len(vs) // 80)
            mw = o.matrix_world
            for i in range(0, len(vs), step):
                w = mw @ vs[i].co
                total += 1
                if (
                    min(w.x - lo.x, hi.x - w.x) <= eps
                    or min(w.y - lo.y, hi.y - w.y) <= eps
                    or min(w.z - lo.z, hi.z - w.z) <= eps
                ):
                    near += 1
        if total and near / total >= 0.7:
            shells.extend(objs)
    return shells


from bpy_extras.object_utils import world_to_camera_view as _world_to_camera_view


def _project_labels(scene, canvas_w, canvas_h, instances=None):
    """One numbered marker per TOP-LEVEL object, at the screen centroid of its
    combined mesh bounds.

    Multi-part objects are built as mesh children parented under a single EMPTY
    root (sofa/lamp/console/...). The old logic labelled only top-level *meshes*
    and skipped EMPTYs + parented meshes, so it returned NOTHING for every
    assembly — handing the VLM judge an empty object
    inventory, which made them hallucinate "objects missing". So we now label the
    ROOT (whatever its type) using the union of its descendant meshes' bounds."""
    MIN_LABEL_AREA_PX = 1500
    out = []
    for obj in scene.objects:
        # One label per top-level object; skip pure helpers and this script's
        # throwaway camera/sun (named _rv_*).
        if obj.parent is not None or obj.type in {"LIGHT", "CAMERA"}:
            continue
        if obj.name.startswith("_rv_"):
            continue
        # Bounds across this object + all its mesh descendants (an EMPTY root has
        # none of its own, so we must walk children).
        instances = instances or {}
        meshes = ([obj] if obj.type == "MESH" or obj in instances else []) + [
            c for c in obj.children_recursive if c.type == "MESH" or c in instances
        ]
        corners = []
        for m in meshes:
            if m.hide_render or not m.bound_box:
                continue
            for c in _corners(m, instances):
                ndc = _world_to_camera_view(scene, scene.camera, c)
                if ndc.z <= 0:
                    continue
                corners.append((int(ndc.x * canvas_w), int((1 - ndc.y) * canvas_h)))
        if len(corners) < 2:
            continue
        x_min = min(c[0] for c in corners); x_max = max(c[0] for c in corners)
        y_min = min(c[1] for c in corners); y_max = max(c[1] for c in corners)
        vis_w = max(0, min(canvas_w, x_max) - max(0, x_min))
        vis_h = max(0, min(canvas_h, y_max) - max(0, y_min))
        if vis_w * vis_h < MIN_LABEL_AREA_PX:
            continue
        cx = max(0, min((x_min + x_max) // 2, canvas_w - 1))
        cy = max(0, min((y_min + y_max) // 2, canvas_h - 1))
        out.append({"name": obj.name, "x": cx, "y": cy, "w": x_max - x_min, "h": y_max - y_min})
    out.sort(key=lambda o: -(o["w"] * o["h"]))
    for i, info in enumerate(out, start=1):
        info["n"] = i
    return out
