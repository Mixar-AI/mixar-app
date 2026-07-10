"""
Advanced mesh analysis handlers for Blender MCP Bridge.
Provides per-object and scene-wide mesh analysis using BMesh.
"""

import bpy
import bmesh
from ...utils.response import ok_response, error_response
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _analyze_object(obj):
    """Run full mesh analysis on a single mesh object and return a data dict."""
    mesh = obj.data

    # Build BMesh for quality metrics
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()

        verts = len(bm.verts)
        edges = len(bm.edges)
        faces = len(bm.faces)

        tris = sum(1 for f in bm.faces if len(f.verts) == 3)
        quads = sum(1 for f in bm.faces if len(f.verts) == 4)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)

        # Manifold check: manifold if every edge has exactly 2 linked faces
        is_manifold = all(len(e.link_faces) == 2 for e in bm.edges)

        # Loose vertices: vertices with no linked edges
        loose_verts = sum(1 for v in bm.verts if not v.link_edges)

        # Degenerate faces: zero-area faces
        degenerate_faces = sum(1 for f in bm.faces if f.calc_area() < 1e-8)

        # Consistent normals: check if any face normal points inward relative to its neighbours
        normals_consistent = True
        for edge in bm.edges:
            linked = edge.link_faces
            if len(linked) == 2:
                dot = linked[0].normal.dot(linked[1].normal)
                if dot < -0.5:
                    normals_consistent = False
                    break
    finally:
        bm.free()

    # Bounding box (local space)
    if mesh.vertices:
        xs = [v.co.x for v in mesh.vertices]
        ys = [v.co.y for v in mesh.vertices]
        zs = [v.co.z for v in mesh.vertices]
        bb_min = [min(xs), min(ys), min(zs)]
        bb_max = [max(xs), max(ys), max(zs)]
        bb_center = [(bb_min[i] + bb_max[i]) / 2 for i in range(3)]
        bb_dims = [bb_max[i] - bb_min[i] for i in range(3)]
    else:
        bb_min = bb_max = bb_center = bb_dims = [0.0, 0.0, 0.0]

    # Materials
    mat_names = [slot.material.name if slot.material else None for slot in obj.material_slots]

    # UVs
    uv_layers = mesh.uv_layers
    uv_info = {
        "has_uvs": len(uv_layers) > 0,
        "layer_count": len(uv_layers),
        "layers": [layer.name for layer in uv_layers],
    }

    # Modifiers
    mod_list = [{"name": m.name, "type": m.type} for m in obj.modifiers]

    return {
        "name": obj.name,
        "object_name": obj.name,
        "geometry": {
            "vertices": verts,
            "edges": edges,
            "faces": faces,
            "tris": tris,
            "quads": quads,
            "ngons": ngons,
        },
        "bounds": {
            "min": bb_min,
            "max": bb_max,
            "center": bb_center,
            "dimensions": bb_dims,
        },
        "quality": {
            "manifold": is_manifold,
            "normals_consistent": normals_consistent,
            "degenerate_faces": degenerate_faces,
            "loose_verts": loose_verts,
        },
        "materials": {
            "count": len(mat_names),
            "names": mat_names,
        },
        "uvs": uv_info,
        "modifiers": {
            "count": len(mod_list),
            "list": mod_list,
        },
    }


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_analyze_mesh(params):
    """
    Analyze a single mesh object.

    Route: POST /api/analysis/mesh

    Required params:
        object_name (str): Name of the mesh object to analyze.
    """
    object_name = params.get("object_name")
    if not object_name:
        return error_response("object_name is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return error_response(f"Object not found: {object_name!r}")
    if obj.type != "MESH":
        return error_response(f"Object {object_name!r} is not a mesh (type: {obj.type})")

    try:
        analysis = _analyze_object(obj)
        return ok_response(analysis)
    except Exception as e:
        return error_response(f"Mesh analysis failed: {e}")


def _handle_analyze_batch(params):
    """
    Analyze mesh objects in the scene with an optional limit to prevent timeouts.

    Route: POST /api/analysis/batch

    Optional params:
        filter_type (str): Object type to analyze. Defaults to 'MESH'.
        limit (int): Maximum number of objects to analyze. Default 50, max 200.
        offset (int): Number of objects to skip. Default 0.
    """
    filter_type = (params.get("filter_type") or "MESH").upper()
    limit = min(int(params.get("limit", 50)), 200)
    offset = max(int(params.get("offset", 0)), 0)

    try:
        all_objects = [obj for obj in bpy.context.scene.objects if obj.type == filter_type]
        total_in_scene = len(all_objects)

        # Apply pagination
        objects = all_objects[offset:offset + limit]

        results = []
        total_verts = 0
        total_faces = 0

        for obj in objects:
            try:
                analysis = _analyze_object(obj)
                results.append(analysis)
                total_verts += analysis["geometry"]["vertices"]
                total_faces += analysis["geometry"]["faces"]
            except Exception as e:
                results.append({"name": obj.name, "object_name": obj.name, "error": str(e)})

        return ok_response({
            "summary": {
                "total_objects_in_scene": total_in_scene,
                "analyzed_count": len(results),
                "total_verts": total_verts,
                "total_faces": total_faces,
                "filter_type": filter_type,
                "limit": limit,
                "offset": offset,
            },
            "objects": results,
        })
    except Exception as e:
        return error_response(f"Batch analysis failed: {e}")


register_handler("analysis", "mesh", _handle_analyze_mesh)
register_handler("analysis", "batch", _handle_analyze_batch)
