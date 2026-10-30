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
- **Skeletons** — a rig whose bones follow a known convention (Tripo's
  auto-rig, Mixamo) gets a bone map onto the engine's humanoid: Godot's
  ``SkeletonProfileHumanoid`` names, Unreal's UE5 Mannequin names. The
  adapter retargets with it, so a clip made on one humanoid plays on another.
- **Readiness** — what would break or degrade on import (an unknown tag value,
  a textured mesh with no UVs, a non-power-of-two texture in Unreal, a physics
  body with no collision), reported as ``issues`` and never fixed silently.

The naming, tag, skeleton and readiness rules are pure functions (pinned
outside Blender); ``build_collision`` alone touches ``bpy``.
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
# An Unreal package's FBX keeps Blender's axes (Z up, Y forward) with the
# axis and unit conversion baked into the vertices (Apply Transform): the
# engine adapter imports each object in its own local space, so its pivot stays
# at its origin, and that import keeps only vertex data. Measured on UE 5.8:
# a 1 x 0.1 x 2 m door is 100 x 10 x 200 cm in local and world-space imports,
# where the plain Unreal preset gives 1 x 0.1 x 2 cm locally. Packages only:
# a scene export for Unreal keeps the plain preset (``export_presets``).
PACKAGE_FBX = {"axis_up": "Z", "axis_forward": "Y", "bake_space_transform": True}
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


def manifest_section(engine: str, objects: list, issues: list, skeletons: list | None = None) -> dict:
    section = {
        "target": engine, "version": MANIFEST_VERSION, "axes": "blender_z_up",
        "objects": objects, "collision_nodes": sum(len((o.get("collision") or {}).get("nodes") or [])
                                                    for o in objects),
        "issues": list(issues),
    }
    if skeletons:
        section["skeletons"] = list(skeletons)
    return section


# ── Skeleton bone maps (P0.4) ──────────────────────────────────────────────
# Source bones in a neutral form: (Godot humanoid bone, UE5 Mannequin bone,
# Tripo auto-rig v3.0 bone, Mixamo bone without its "mixamorig:" prefix).
# Tripo names are the real 78-bone rig's (uat4, 28 Oct). None = no such bone.
_BODY = [
    ("Root", "root", "BoneRoot", None),
    ("Hips", "pelvis", "Hip", "Hips"),
    ("Spine", "spine_01", "Waist", "Spine"),
    ("Chest", "spine_03", "Spine01", "Spine1"),
    ("UpperChest", "spine_05", "Spine02", "Spine2"),
    ("Neck", "neck_01", "NeckTwist01", "Neck"),
    (None, "neck_02", "NeckTwist02", None),  # closes the Mannequin's Neck chain
    ("Head", "head", "Head", "Head"),
    ("LeftEye", None, "L_Eye", "LeftEye"),  # the Mannequin has no eye bones
    ("RightEye", None, "R_Eye", "RightEye"),
]
_SIDED = [  # {side} is L/R (Tripo), Left/Right (Godot, Mixamo), l/r (UE)
    ("{Side}Shoulder", "clavicle_{s}", "{L}_Clavicle", "{Side}Shoulder"),
    ("{Side}UpperArm", "upperarm_{s}", "{L}_Upperarm", "{Side}Arm"),
    ("{Side}LowerArm", "lowerarm_{s}", "{L}_Forearm", "{Side}ForeArm"),
    ("{Side}Hand", "hand_{s}", "{L}_Hand", "{Side}Hand"),
    ("{Side}UpperLeg", "thigh_{s}", "{L}_Thigh", "{Side}UpLeg"),
    ("{Side}LowerLeg", "calf_{s}", "{L}_Calf", "{Side}Leg"),
    ("{Side}Foot", "foot_{s}", "{L}_Foot", "{Side}Foot"),
    ("{Side}Toes", "ball_{s}", "{L}_ToeBase", "{Side}ToeBase"),
]
_FINGERS = [  # Godot finger, its three joints, UE finger, Tripo finger, Mixamo finger
    ("Thumb", ("Metacarpal", "Proximal", "Distal"), "thumb", "Thumb", "Thumb"),
    ("Index", ("Proximal", "Intermediate", "Distal"), "index", "Index", "Index"),
    ("Middle", ("Proximal", "Intermediate", "Distal"), "middle", "Mid", "Middle"),
    ("Ring", ("Proximal", "Intermediate", "Distal"), "ring", "Ring", "Ring"),
    ("Little", ("Proximal", "Intermediate", "Distal"), "pinky", "Pinky", "Pinky"),
]
_TRIPO_ONLY = [  # twist helpers the Mannequin also has
    ("upperarm_twist_01_{s}", "{L}_UpperarmTwist01"), ("upperarm_twist_02_{s}", "{L}_UpperarmTwist02"),
    ("lowerarm_twist_01_{s}", "{L}_ForearmTwist01"), ("lowerarm_twist_02_{s}", "{L}_ForearmTwist02"),
    ("thigh_twist_01_{s}", "{L}_ThighTwist01"), ("thigh_twist_02_{s}", "{L}_ThighTwist02"),
    ("calf_twist_01_{s}", "{L}_CalfTwist01"), ("calf_twist_02_{s}", "{L}_CalfTwist02"),
]
PROFILES = {"godot": "godot_humanoid", "unreal": "ue5_mannequin", "uefn": "ue5_mannequin"}
_MIXAMO_PREFIX = ("mixamorig:", "mixamorig_")


def _rows():
    """(godot, ue, tripo, mixamo) for every mapped bone."""
    rows = list(_BODY)
    for side, s, l in (("Left", "l", "L"), ("Right", "r", "R")):
        for row in _SIDED:
            rows.append(tuple(None if v is None else v.format(Side=side, s=s, L=l) for v in row))
        for finger, joints, ue, tripo, mixamo in _FINGERS:
            for n, joint in enumerate(joints, 1):
                rows.append((f"{side}{finger}{joint}", f"{ue}_0{n}_{s}", f"{l}_{tripo}{n}",
                             f"{side}Hand{mixamo}{n}"))
        for ue, tripo in _TRIPO_ONLY:
            rows.append((None, ue.format(s=s), tripo.format(L=l), None))
    return rows


def skeleton_naming(bone_names) -> tuple[str, str] | None:
    """``(naming, prefix)`` when the bones follow a known convention."""
    names = set(bone_names)
    if {"BoneRoot", "Hip", "L_Upperarm", "R_Forearm", "L_Thigh"} <= names:
        return "tripo", ""
    for prefix in _MIXAMO_PREFIX:
        if {prefix + "Hips", prefix + "LeftArm", prefix + "RightUpLeg"} <= names:
            return "mixamo", prefix
    return None


def skeleton_map(engine: str, armature_name: str, bone_names) -> dict | None:
    """The manifest entry mapping one armature's bones onto the engine's
    humanoid (target bone -> this rig's bone), or None for an unknown rig."""
    hit = skeleton_naming(bone_names)
    profile = PROFILES.get(engine)
    if hit is None or profile is None:
        return None
    naming, prefix = hit
    names = set(bone_names)
    target = 0 if profile == "godot_humanoid" else 1
    source = 2 if naming == "tripo" else 3
    bones = {}
    for row in _rows():
        if row[target] is None or row[source] is None:
            continue
        bone = prefix + row[source]
        if bone in names:
            bones[row[target]] = bone
    return {"armature": armature_name, "naming": naming, "profile": profile, "bones": bones}


def skeleton_entry(engine: str, armature_name: str, bone_names) -> dict:
    """The manifest entry for one armature: its bone map when the rig follows
    a known naming, else ``naming: "custom"`` with no map — the engine still
    imports it as a skinned character, it just retargets no humanoid clips."""
    return skeleton_map(engine, armature_name, bone_names) or {
        "armature": armature_name, "naming": "custom", "profile": PROFILES.get(engine), "bones": {}}


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
