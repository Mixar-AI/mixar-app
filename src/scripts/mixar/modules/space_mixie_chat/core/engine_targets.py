# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game-engine targets for ``export_asset`` packages (``engine=``).

A package written for an engine imports there with no manual fixes and keeps
what each object is for:

- **Collision** — a hull per mesh, named the way the engine's importer reads
  it: Godot's ``-convcolonly`` / ``-colonly`` node suffixes (a collision-only
  StaticBody3D child), Unreal's (and UEFN's) ``UCX_<mesh>_NN`` convex hulls in
  the same FBX. A ``mesh`` shape in Unreal is no extra mesh: the manifest says
  ``complex_as_simple`` and the engine adapter sets it on import.
- **Game semantics** — ``mixar_*`` custom properties on the deliverable
  objects (``mixar_role``, ``mixar_body``, ``mixar_pivot``, ``mixar_nav``,
  ``mixar_light``, ``mixar_collision``), validated here and written to the
  manifest's ``engine`` section, the record an engine adapter reads. glTF
  packages also carry them as node extras (Godot reads those as metadata).
  Axes in ``mixar_pivot`` are Blender's (Z up); the adapter converts them.
- **Readiness** — what would break or degrade on import (an unknown tag value,
  a textured mesh with no UVs, a non-power-of-two texture in Unreal, a physics
  body with no collision), reported as ``issues`` and never fixed silently.

The naming, tag and readiness rules are pure functions (pinned outside
Blender); ``build_collision`` alone touches ``bpy``.
"""

from __future__ import annotations

ENGINES = ("godot", "unreal", "uefn")
# The importer each engine family reads names with.
_UNREAL_FAMILY = ("unreal", "uefn")
ENGINE_FORMATS = {"godot": ("glb", "gltf", "fbx"), "unreal": ("fbx",), "uefn": ("fbx",)}
MANIFEST_VERSION = 1
TAG_PREFIX = "mixar_"
TAGS = {
    "role": ("prop", "player", "enemy", "door", "pickup", "spawn", "trigger",
             "hazard", "checkpoint", "goal"),
    "body": ("static", "rigid", "kinematic", "none"),
    "pivot": ("hinge_x", "hinge_y", "hinge_z", "slide_x", "slide_y", "slide_z"),
    "nav": ("walkable", "obstacle", "ignore"),
    "light": ("baked", "dynamic"),
    "collision": ("box", "convex", "mesh", "none"),
}
# Convex hulls are built from at most this many source vertices (strided), so
# a dense scan never stalls the export; the hull of a subset stays inside the
# true hull.
MAX_HULL_INPUT = 4096


def normalise_engine(value) -> str | None:
    engine = str(value or "").strip().lower()
    return engine if engine in ENGINES else None


def read_tags(obj, name=None) -> tuple[dict, list]:
    """``mixar_*`` properties of ``obj`` → (valid tags, issues). Unknown
    values are reported, never guessed into a neighbour. ``name`` labels the
    issues (the package renames originals while it exports)."""
    tags, issues = {}, []
    name = name or getattr(obj, "name", "?")
    for key, allowed in TAGS.items():
        raw = obj.get(TAG_PREFIX + key)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if value in allowed:
            tags[key] = value
        else:
            issues.append(f"{name}: {TAG_PREFIX}{key} '{raw}' is not one of {', '.join(allowed)}.")
    return tags, issues


def collision_shape(tags: dict, skinned: bool) -> str:
    """The hull a mesh gets: an explicit ``mixar_collision`` wins; a skinned
    mesh (a character, collided by its controller) and ``body: none`` get
    none; anything else a convex hull."""
    if "collision" in tags:
        return tags["collision"]
    if skinned or tags.get("body") == "none":
        return "none"
    return "convex"


def collision_names(engine: str, mesh_name: str, shape: str) -> list:
    """Names of the collision meshes ``shape`` adds for ``mesh_name``."""
    if shape == "none":
        return []
    if engine == "godot":
        suffix = "-colonly" if shape == "mesh" else "-convcolonly"
        return [f"{mesh_name}_col{suffix}"]
    if engine in _UNREAL_FAMILY:
        # A trimesh is the render mesh itself (complex as simple), no UCX.
        return [] if shape == "mesh" else [f"UCX_{mesh_name}_00"]
    return []


def collision_entry(engine: str, mesh_name: str, shape: str, names: list) -> dict:
    entry = {"shape": shape, "nodes": list(names)}
    if engine in _UNREAL_FAMILY and shape == "mesh":
        entry["complex_as_simple"] = True
    return entry


def readiness_issues(engine: str, *, textures=(), meshes=(), objects=()) -> list:
    """What would degrade on import into ``engine``.

    ``textures``: (file name, (w, h)); ``meshes``: (name, has_uv,
    uses_images); ``objects``: manifest object entries (tags + collision).
    """
    issues = []
    if engine in _UNREAL_FAMILY:
        for fname, size in textures:
            w, h = (int(size[0]), int(size[1])) if size else (0, 0)
            if w and h and not (_pow2(w) and _pow2(h)):
                issues.append(f"{fname} is {w}x{h}; Unreal gives non-power-of-two textures "
                              "no mipmaps and no streaming.")
    for name, has_uv, uses_images in meshes:
        if uses_images and not has_uv:
            issues.append(f"{name} has image textures but no UV map.")
    for entry in objects:
        body = entry.get("body")
        shape = (entry.get("collision") or {}).get("shape")
        if body in ("static", "rigid", "kinematic") and shape == "none":
            issues.append(f"{entry.get('name')}: mixar_body '{body}' has no collision "
                          "(mixar_collision 'none').")
    return issues


def manifest_section(engine: str, objects: list, issues: list) -> dict:
    return {
        "target": engine, "version": MANIFEST_VERSION, "axes": "blender_z_up",
        "objects": objects, "collision_nodes": sum(len((o.get("collision") or {}).get("nodes") or [])
                                                    for o in objects),
        "issues": list(issues),
    }


def _pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


# ---------------------------------------------------------------------------
# Blender side
# ---------------------------------------------------------------------------

def build_collision(engine: str, copy, shape: str, names: list, col) -> list:
    """Collision mesh objects for the world-baked ``copy``, linked into the
    package's temp collection ``col`` (so its cleanup removes them). Godot
    hulls are parented to the copy (its body follows the mesh); Unreal hulls
    stay siblings, matched by name."""
    import bpy

    out = []
    for name in names:
        if shape == "mesh":
            me = copy.data.copy()
            me.name = name
            me.materials.clear()
        else:
            me = _hull_mesh(copy, name, box=shape == "box")
        obj = bpy.data.objects.new(name, me)
        col.objects.link(obj)
        # The hull is built in the copy's own space: a Godot hull is its child,
        # an Unreal UCX sibling stands where the copy stands.
        if engine == "godot":
            obj.parent = copy
        else:
            obj.matrix_world = copy.matrix_world.copy()
        out.append(obj)
    return out


def _hull_mesh(copy, name: str, box: bool):
    import bmesh
    import bpy
    import numpy as np

    verts = copy.data.vertices
    co = np.empty(len(verts) * 3, dtype=np.float32)
    verts.foreach_get("co", co)
    co = co.reshape(-1, 3)
    bm = bmesh.new()
    try:
        if not box and len(co) >= 4:
            step = max(1, len(co) // MAX_HULL_INPUT)
            for p in co[::step]:
                bm.verts.new(p.tolist())
            hull = bmesh.ops.convex_hull(bm, input=bm.verts[:])
            stray = list({*hull.get("geom_interior", []), *hull.get("geom_unused", [])})
            stray = [g for g in stray if isinstance(g, bmesh.types.BMVert)]
            if stray:
                bmesh.ops.delete(bm, geom=stray, context="VERTS")
            box = len(bm.faces) < 4  # flat or degenerate: fall back to the bounds box
            if box:
                bm.clear()
        if box:
            lo = co.min(0) if len(co) else np.zeros(3)
            hi = co.max(0) if len(co) else np.zeros(3)
            size = np.maximum(hi - lo, 0.01)  # a plane still gets a thin slab
            centre = (hi + lo) / 2
            bmesh.ops.create_cube(bm, size=1.0)
            for v in bm.verts:
                v.co = [centre[i] + v.co[i] * size[i] for i in range(3)]
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
    finally:
        bm.free()
    return me
