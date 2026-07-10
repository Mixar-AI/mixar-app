"""
Validation handlers for Blender MCP Bridge.
Provides mesh validation, export-readiness checks, and full scene validation.
"""

import math
import bpy
import bmesh
from mathutils import Vector
from mathutils.kdtree import KDTree
from ...utils.response import ok_response, error_response, not_found
from .. import register_handler


# ─── Constants ─────────────────────────────────────────────────────────────────

ALL_MESH_CHECKS = (
    "manifold", "normals", "ngons", "poles", "degenerate",
    "loose", "uvs", "scale", "doubles",
)

DOUBLES_THRESHOLD = 0.0001
DEGENERATE_AREA_THRESHOLD = 1e-8
UNIT_SCALE_THRESHOLD = 0.0001


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH type object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', expected 'MESH'."
        )
    return obj, None


def _run_mesh_checks(obj, requested_checks):
    """
    Run mesh quality checks on a single mesh object using BMesh.

    Returns a list of check result dicts:
        {name, status: "pass"/"warning"/"error", details}
    """
    check_results = []
    mesh = obj.data

    # ── scale ──────────────────────────────────────────────────────────────────
    if "scale" in requested_checks:
        sx, sy, sz = obj.scale
        is_unit = (
            abs(sx - 1.0) <= UNIT_SCALE_THRESHOLD and
            abs(sy - 1.0) <= UNIT_SCALE_THRESHOLD and
            abs(sz - 1.0) <= UNIT_SCALE_THRESHOLD
        )
        check_results.append({
            "name": "scale",
            "status": "pass" if is_unit else "warning",
            "details": f"Scale: ({sx:.4f}, {sy:.4f}, {sz:.4f}). "
                       + ("" if is_unit else "Non-unit scale detected — apply scale before export."),
        })

    # ── uvs ────────────────────────────────────────────────────────────────────
    if "uvs" in requested_checks:
        uv_count = len(mesh.uv_layers)
        check_results.append({
            "name": "uvs",
            "status": "pass" if uv_count > 0 else "warning",
            "details": f"UV layers: {uv_count}. "
                       + ("" if uv_count > 0 else "No UV layers found — textures may not export correctly."),
        })

    # For topological checks we need BMesh
    needs_bmesh = bool(requested_checks & {
        "manifold", "normals", "ngons", "poles", "degenerate", "loose", "doubles"
    })

    if not needs_bmesh:
        return check_results

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # ── manifold ───────────────────────────────────────────────────────────
        if "manifold" in requested_checks:
            non_manifold_edges = [
                e for e in bm.edges
                if len(e.link_faces) != 2 and len(e.link_faces) != 0
            ]
            boundary_edges = [e for e in bm.edges if len(e.link_faces) == 1]
            wire_edges = [e for e in bm.edges if len(e.link_faces) == 0]

            if boundary_edges or wire_edges:
                status = "error"
                details = (
                    f"Non-manifold geometry detected: "
                    f"{len(boundary_edges)} boundary edge(s), "
                    f"{len(wire_edges)} wire edge(s)."
                )
            elif non_manifold_edges:
                status = "warning"
                details = f"{len(non_manifold_edges)} non-manifold edge(s) found."
            else:
                status = "pass"
                details = "Mesh is manifold."

            check_results.append({"name": "manifold", "status": status, "details": details})

        # ── normals ────────────────────────────────────────────────────────────
        if "normals" in requested_checks:
            # Count faces whose computed normal opposes average of its vertex normals
            flipped_count = 0
            for face in bm.faces:
                face_normal = face.normal
                if face_normal is None or len(face.verts) == 0:
                    continue
                valid_normals = [v.normal for v in face.verts if v.normal is not None]
                if not valid_normals:
                    continue
                avg_vert_normal = sum(valid_normals, Vector((0, 0, 0))) / len(valid_normals)
                if face_normal.dot(avg_vert_normal) < 0:
                    flipped_count += 1

            check_results.append({
                "name": "normals",
                "status": "pass" if flipped_count == 0 else "warning",
                "details": f"Flipped normals detected on {flipped_count} face(s)."
                           if flipped_count > 0 else "Normals appear consistent.",
            })

        # ── ngons ──────────────────────────────────────────────────────────────
        if "ngons" in requested_checks:
            ngon_faces = [f for f in bm.faces if len(f.verts) > 4]
            check_results.append({
                "name": "ngons",
                "status": "pass" if not ngon_faces else "warning",
                "details": f"{len(ngon_faces)} N-gon face(s) found (>4 vertices). "
                           "May cause issues with some export targets."
                           if ngon_faces else "No N-gons found.",
            })

        # ── poles ──────────────────────────────────────────────────────────────
        if "poles" in requested_checks:
            pole_verts = [v for v in bm.verts if len(v.link_edges) > 5]
            check_results.append({
                "name": "poles",
                "status": "pass" if not pole_verts else "warning",
                "details": f"{len(pole_verts)} high-valence pole vertex/vertices (>5 edges). "
                           "May indicate topology issues."
                           if pole_verts else "No high-valence poles found.",
            })

        # ── degenerate ─────────────────────────────────────────────────────────
        if "degenerate" in requested_checks:
            degen_faces = [f for f in bm.faces if f.calc_area() < DEGENERATE_AREA_THRESHOLD]
            check_results.append({
                "name": "degenerate",
                "status": "pass" if not degen_faces else "error",
                "details": f"{len(degen_faces)} degenerate face(s) with near-zero area found."
                           if degen_faces else "No degenerate faces found.",
            })

        # ── loose ──────────────────────────────────────────────────────────────
        if "loose" in requested_checks:
            loose_verts = [v for v in bm.verts if not v.link_edges]
            check_results.append({
                "name": "loose",
                "status": "pass" if not loose_verts else "warning",
                "details": f"{len(loose_verts)} loose vertex/vertices (no edges) found."
                           if loose_verts else "No loose vertices found.",
            })

        # ── doubles ────────────────────────────────────────────────────────────
        if "doubles" in requested_checks:
            vert_count = len(bm.verts)
            if vert_count == 0:
                check_results.append({
                    "name": "doubles",
                    "status": "pass",
                    "details": "No vertices to check.",
                })
            else:
                kd = KDTree(vert_count)
                for i, v in enumerate(bm.verts):
                    kd.insert(v.co, i)
                kd.balance()

                seen = set()
                double_count = 0
                for v in bm.verts:
                    if v.index in seen:
                        continue
                    neighbors = kd.find_range(v.co, DOUBLES_THRESHOLD)
                    # neighbors includes the vertex itself
                    for _, idx, _ in neighbors:
                        if idx != v.index:
                            seen.add(idx)
                            double_count += 1

                check_results.append({
                    "name": "doubles",
                    "status": "pass" if double_count == 0 else "warning",
                    "details": f"{double_count} duplicate/overlapping vertex pair(s) found "
                               f"(threshold: {DOUBLES_THRESHOLD})."
                               if double_count > 0 else "No duplicate vertices found.",
                })

    finally:
        bm.free()

    return check_results


# ─── Core validation handler ───────────────────────────────────────────────────

def _handle_validate_mesh(params):
    """
    Validate mesh quality with configurable checks.

    Route: POST /api/validation/mesh

    Required params:
        object_name (str): Name of the mesh object to validate.

    Optional params:
        checks (list[str]): Checks to run. Defaults to all checks.
            Valid: manifold, normals, ngons, poles, degenerate, loose, uvs, scale, doubles

    Returns:
        {object, passed, warnings, errors, checks: [{name, status, details}]}
    """
    object_name = params.get("object_name", "").strip()
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    requested_raw = params.get("checks")
    if requested_raw:
        requested_checks = set(c.lower() for c in requested_raw)
        unknown = requested_checks - set(ALL_MESH_CHECKS)
        if unknown:
            return error_response(
                f"Unknown check(s): {', '.join(sorted(unknown))}. "
                f"Valid checks: {', '.join(ALL_MESH_CHECKS)}."
            )
    else:
        requested_checks = set(ALL_MESH_CHECKS)

    try:
        check_results = _run_mesh_checks(obj, requested_checks)
    except Exception as e:
        return error_response(f"Failed to validate mesh '{object_name}': {e}")

    warnings = [c for c in check_results if c["status"] == "warning"]
    errors = [c for c in check_results if c["status"] == "error"]
    passed = len(errors) == 0

    return ok_response({
        "object": object_name,
        "passed": passed,
        "warning_count": len(warnings),
        "error_count": len(errors),
        "warnings": [c["name"] for c in warnings],
        "errors": [c["name"] for c in errors],
        "checks": check_results,
    })


def _handle_validate_export_ready(params):
    """
    Pre-export readiness checklist for one or all mesh objects.

    Route: POST /api/validation/export-ready

    Optional params:
        object_name (str): Specific mesh to check. Omit to check all meshes.
        target (str): 'UNITY' | 'UNREAL' | 'GLTF' | 'GENERIC'

    Returns:
        {ready, target, object_count, issues: [{object, check, severity, message}]}
    """
    object_name = params.get("object_name", "").strip()
    target = (params.get("target") or "GENERIC").upper()
    valid_targets = ("UNITY", "UNREAL", "GLTF", "GENERIC")
    if target not in valid_targets:
        return error_response(
            f"Invalid target '{target}'. Must be one of: {', '.join(valid_targets)}."
        )

    # Determine which objects to check
    if object_name:
        obj, err = _get_mesh_object(object_name)
        if err:
            return err
        objects_to_check = [obj]
    else:
        objects_to_check = [o for o in bpy.data.objects if o.type == "MESH"]
        if not objects_to_check:
            return ok_response({
                "ready": True,
                "target": target,
                "object_count": 0,
                "issues": [],
                "message": "No mesh objects found in scene.",
            })

    # Define which checks matter per target
    required_checks = {
        "UNITY":   {"applied_transforms", "clean_normals", "has_uvs", "no_ngons", "manifold", "proper_scale", "materials_assigned"},
        "UNREAL":  {"applied_transforms", "clean_normals", "has_uvs", "no_ngons", "manifold", "proper_scale", "materials_assigned"},
        "GLTF":    {"applied_transforms", "clean_normals", "has_uvs", "manifold", "materials_assigned"},
        "GENERIC": {"applied_transforms", "clean_normals", "manifold", "proper_scale"},
    }
    checks_for_target = required_checks[target]

    issues = []

    for obj in objects_to_check:
        mesh = obj.data

        # applied_transforms — rotation and scale should be applied (identity-ish)
        if "applied_transforms" in checks_for_target:
            scale = obj.scale
            rotation = obj.rotation_euler
            if (
                abs(scale.x - 1.0) > UNIT_SCALE_THRESHOLD or
                abs(scale.y - 1.0) > UNIT_SCALE_THRESHOLD or
                abs(scale.z - 1.0) > UNIT_SCALE_THRESHOLD
            ):
                issues.append({
                    "object": obj.name,
                    "object_name": obj.name,
                    "check": "applied_transforms",
                    "severity": "warning",
                    "message": f"Scale ({scale.x:.3f}, {scale.y:.3f}, {scale.z:.3f}) is not applied. Apply scale before export.",
                })
            rot_threshold = 0.001
            if (
                abs(rotation.x) > rot_threshold or
                abs(rotation.y) > rot_threshold or
                abs(rotation.z) > rot_threshold
            ):
                issues.append({
                    "object": obj.name,
                    "object_name": obj.name,
                    "check": "applied_transforms",
                    "severity": "warning",
                    "message": f"Rotation is not applied. Apply rotation before export.",
                })

        # proper_scale — overall scale check (same as applied_transforms scale)
        if "proper_scale" in checks_for_target:
            scale = obj.scale
            if (
                abs(scale.x - 1.0) > UNIT_SCALE_THRESHOLD or
                abs(scale.y - 1.0) > UNIT_SCALE_THRESHOLD or
                abs(scale.z - 1.0) > UNIT_SCALE_THRESHOLD
            ):
                # Avoid duplicate if already added above
                existing = [i for i in issues if i["object"] == obj.name and i["check"] == "proper_scale"]
                if not existing:
                    issues.append({
                        "object": obj.name,
                        "object_name": obj.name,
                        "check": "proper_scale",
                        "severity": "warning",
                        "message": "Non-unit scale detected. Apply scale for reliable export.",
                    })

        # has_uvs
        if "has_uvs" in checks_for_target:
            if len(mesh.uv_layers) == 0:
                issues.append({
                    "object": obj.name,
                    "object_name": obj.name,
                    "check": "has_uvs",
                    "severity": "error" if target in ("UNITY", "UNREAL") else "warning",
                    "message": "No UV layers found. Textures will not export correctly.",
                })

        # materials_assigned
        if "materials_assigned" in checks_for_target:
            if len(obj.material_slots) == 0 or all(s.material is None for s in obj.material_slots):
                issues.append({
                    "object": obj.name,
                    "object_name": obj.name,
                    "check": "materials_assigned",
                    "severity": "warning",
                    "message": "No materials assigned to object.",
                })

        # Topological checks via BMesh
        needs_bm = bool(checks_for_target & {"clean_normals", "no_ngons", "manifold"})
        if needs_bm:
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

                if "manifold" in checks_for_target:
                    boundary_edges = [e for e in bm.edges if len(e.link_faces) == 1]
                    wire_edges = [e for e in bm.edges if len(e.link_faces) == 0]
                    if boundary_edges or wire_edges:
                        issues.append({
                            "object": obj.name,
                            "object_name": obj.name,
                            "check": "manifold",
                            "severity": "error",
                            "message": (
                                f"Non-manifold geometry: "
                                f"{len(boundary_edges)} boundary edge(s), "
                                f"{len(wire_edges)} wire edge(s)."
                            ),
                        })

                if "no_ngons" in checks_for_target:
                    ngon_faces = [f for f in bm.faces if len(f.verts) > 4]
                    if ngon_faces:
                        issues.append({
                            "object": obj.name,
                            "object_name": obj.name,
                            "check": "no_ngons",
                            "severity": "warning",
                            "message": f"{len(ngon_faces)} N-gon(s) found. May cause shading issues.",
                        })

                if "clean_normals" in checks_for_target:
                    flipped = 0
                    for face in bm.faces:
                        if len(face.verts) == 0:
                            continue
                        fn = face.normal
                        if fn is None:
                            continue
                        valid_normals = [v.normal for v in face.verts if v.normal is not None]
                        if not valid_normals:
                            continue
                        avg = sum(valid_normals, Vector((0, 0, 0))) / len(valid_normals)
                        if fn.dot(avg) < 0:
                            flipped += 1
                    if flipped > 0:
                        issues.append({
                            "object": obj.name,
                            "object_name": obj.name,
                            "check": "clean_normals",
                            "severity": "warning",
                            "message": f"{flipped} face(s) with potentially flipped normals.",
                        })
            finally:
                bm.free()

    has_errors = any(i["severity"] == "error" for i in issues)
    ready = not has_errors

    return ok_response({
        "ready": ready,
        "target": target,
        "object_count": len(objects_to_check),
        "issue_count": len(issues),
        "issues": issues,
    })


# ─── Advanced validation handler ───────────────────────────────────────────────

def _handle_validate_scene(params):
    """
    Full scene-wide validation pass.

    Route: POST /api/validation/scene

    Optional params:
        checks (list[str]): Checks to run. Defaults to all.
            Valid: naming, transforms, materials, orphans, visibility

    Returns:
        {summary, object_count, issue_count, checks_run, objects: [{name, type, issues}]}
    """
    valid_checks = ("naming", "transforms", "materials", "orphans", "visibility")
    requested_raw = params.get("checks")
    if requested_raw:
        requested_checks = set(c.lower() for c in requested_raw)
        unknown = requested_checks - set(valid_checks)
        if unknown:
            return error_response(
                f"Unknown check(s): {', '.join(sorted(unknown))}. "
                f"Valid: {', '.join(valid_checks)}."
            )
    else:
        requested_checks = set(valid_checks)

    try:
        scene = bpy.context.scene
        results_per_object = []
        total_issues = 0

        for obj in bpy.data.objects:
            obj_issues = []

            # naming — check for default Blender names like "Cube", "Sphere.001", etc.
            if "naming" in requested_checks:
                default_prefixes = (
                    "Cube", "Sphere", "Cylinder", "Cone", "Torus", "Plane",
                    "Camera", "Light", "Empty", "Armature", "Grid", "Circle",
                    "Icosphere", "Monkey", "Text", "Lamp",
                )
                base_name = obj.name.split(".")[0]
                if any(base_name == prefix for prefix in default_prefixes):
                    obj_issues.append({
                        "check": "naming",
                        "severity": "warning",
                        "message": f"Object uses a default Blender name '{obj.name}'. Consider renaming for clarity.",
                    })

            # transforms — unapplied scale or rotation
            if "transforms" in requested_checks:
                scale = obj.scale
                rotation = obj.rotation_euler
                if (
                    abs(scale.x - 1.0) > UNIT_SCALE_THRESHOLD or
                    abs(scale.y - 1.0) > UNIT_SCALE_THRESHOLD or
                    abs(scale.z - 1.0) > UNIT_SCALE_THRESHOLD
                ):
                    obj_issues.append({
                        "check": "transforms",
                        "severity": "warning",
                        "message": f"Scale ({scale.x:.3f}, {scale.y:.3f}, {scale.z:.3f}) not applied.",
                    })
                rot_threshold = 0.001
                if (
                    abs(rotation.x) > rot_threshold or
                    abs(rotation.y) > rot_threshold or
                    abs(rotation.z) > rot_threshold
                ):
                    obj_issues.append({
                        "check": "transforms",
                        "severity": "warning",
                        "message": "Rotation not applied.",
                    })

            # materials — mesh objects should have at least one material
            if "materials" in requested_checks and obj.type == "MESH":
                if len(obj.material_slots) == 0 or all(s.material is None for s in obj.material_slots):
                    obj_issues.append({
                        "check": "materials",
                        "severity": "warning",
                        "message": "Mesh has no materials assigned.",
                    })

            # visibility — objects hidden in render but visible in viewport (or vice versa)
            if "visibility" in requested_checks:
                if obj.hide_viewport != obj.hide_render:
                    state = "hidden in render but visible in viewport" if not obj.hide_render else "hidden in viewport but visible in render"
                    obj_issues.append({
                        "check": "visibility",
                        "severity": "warning",
                        "message": f"Visibility mismatch: object is {state}.",
                    })

            if obj_issues:
                total_issues += len(obj_issues)
                results_per_object.append({
                    "name": obj.name,
                    "object_name": obj.name,
                    "type": obj.type,
                    "issue_count": len(obj_issues),
                    "issues": obj_issues,
                })

        # orphans check — runs globally, not per-object
        orphan_report = []
        if "orphans" in requested_checks:
            orphan_meshes = [m.name for m in bpy.data.meshes if m.users == 0]
            orphan_materials = [m.name for m in bpy.data.materials if m.users == 0]
            orphan_images = [i.name for i in bpy.data.images if i.users == 0]
            orphan_actions = [a.name for a in bpy.data.actions if a.users == 0]

            if orphan_meshes:
                orphan_report.append({
                    "type": "orphan_data",
                    "severity": "warning",
                    "message": f"{len(orphan_meshes)} orphan mesh data block(s): {', '.join(orphan_meshes[:5])}{'...' if len(orphan_meshes) > 5 else ''}",
                })
            if orphan_materials:
                orphan_report.append({
                    "type": "orphan_data",
                    "severity": "warning",
                    "message": f"{len(orphan_materials)} orphan material(s): {', '.join(orphan_materials[:5])}{'...' if len(orphan_materials) > 5 else ''}",
                })
            if orphan_images:
                orphan_report.append({
                    "type": "orphan_data",
                    "severity": "warning",
                    "message": f"{len(orphan_images)} orphan image(s): {', '.join(orphan_images[:5])}{'...' if len(orphan_images) > 5 else ''}",
                })
            if orphan_actions:
                orphan_report.append({
                    "type": "orphan_data",
                    "severity": "warning",
                    "message": f"{len(orphan_actions)} orphan action(s): {', '.join(orphan_actions[:5])}{'...' if len(orphan_actions) > 5 else ''}",
                })
            total_issues += len(orphan_report)

        return ok_response({
            "scene": scene.name,
            "object_count": len(bpy.data.objects),
            "issue_count": total_issues,
            "checks_run": sorted(requested_checks),
            "objects_with_issues": len(results_per_object),
            "orphan_issues": orphan_report,
            "objects": results_per_object,
        })

    except Exception as e:
        return error_response(f"Failed to validate scene: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("validation", "mesh", _handle_validate_mesh)
register_handler("validation", "export-ready", _handle_validate_export_ready)
register_handler("validation", "scene", _handle_validate_scene)
