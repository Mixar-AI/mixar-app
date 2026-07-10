"""
Advanced modeling handlers for Blender MCP Bridge.
Provides: mesh/from-data, mesh/edit, mesh/select, mesh/separate, mesh/merge, mesh/normals, mesh/boolean
"""

import math
import bpy
import bmesh
from ...utils.response import ok_response, error_response, not_found
from ...utils.compat import get_auto_smooth_method, is_blender_4, merge_vertices
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _bmesh_collect_edge_loop(bm, start_edge):
    """Return a list of edges forming the loop that contains *start_edge*.

    Uses quad-walking: follows edges that share exactly one quad face with
    the previous edge and crosses through the opposite edge of that quad.
    """
    def _walk(edge, prev_face, visited_set):
        edges = []
        current = edge
        came_from = prev_face
        while current is not None and current.index not in visited_set:
            visited_set.add(current.index)
            edges.append(current)
            next_edge = None
            for face in current.link_faces:
                if face == came_from:
                    continue
                if len(face.verts) != 4:
                    continue
                for e in face.edges:
                    if e == current:
                        continue
                    if len(set(current.verts) & set(e.verts)) == 0:
                        next_edge = e
                        came_from = face
                        break
                if next_edge is not None:
                    break
            current = next_edge
        return edges

    visited = {start_edge.index}
    result = [start_edge]

    for face in start_edge.link_faces:
        if len(face.verts) != 4:
            continue
        opposite = None
        for e in face.edges:
            if e == start_edge:
                continue
            if len(set(start_edge.verts) & set(e.verts)) == 0:
                opposite = e
                break
        if opposite is not None:
            result.extend(_walk(opposite, face, visited))

    return result


def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Mesh object")
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _enter_edit_mode(obj):
    """Ensure the object is active and in Edit Mode."""
    ensure_context_for_object(obj)
    if bpy.context.mode != "EDIT_MESH":
        bpy.ops.object.mode_set(mode="EDIT")


def _exit_edit_mode():
    """Switch back to Object Mode."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_mesh_from_data(params):
    """
    Create a new mesh object from raw vertex/face data.
    Route: POST /api/mesh/from-data
    """
    try:
        name = params.get("name", "CustomMesh")
        vertices = params.get("vertices", [])
        faces = params.get("faces", [])
        edges = params.get("edges", [])

        if not vertices:
            return error_response("Parameter 'vertices' must be a non-empty list.")
        if faces is None:
            faces = []

        # Convert to plain Python tuples (from_pydata expects sequences of sequences)
        verts_tuples = [tuple(v) for v in vertices]
        edges_tuples = [tuple(e) for e in edges]
        faces_tuples = [tuple(f) for f in faces]

        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts_tuples, edges_tuples, faces_tuples)
        mesh.update()

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)

        # Make active so subsequent operations can target it
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        dims = obj.dimensions
        return ok_response({
            "object_name": obj.name,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.polygons),
            "edge_count": len(mesh.edges),
            "dimensions": [round(dims.x, 6), round(dims.y, 6), round(dims.z, 6)],
        })
    except Exception as e:
        return error_response(f"Failed to create mesh from data: {e}")


def _handle_mesh_edit(params):
    """
    Perform a mesh edit operation on an existing mesh object.
    Route: POST /api/mesh/edit
    """
    object_name = params.get("object_name")
    operation = params.get("operation", "").upper()
    op_params = params.get("parameters") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not operation:
        return error_response("Parameter 'operation' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)
        mesh_before = len(obj.data.vertices)

        with temp_override("VIEW_3D"):
            if operation == "EXTRUDE":
                value = op_params.get("value", 0.1)
                bpy.ops.mesh.extrude_region_move(
                    TRANSFORM_OT_translate={"value": (0, 0, value)}
                )

            elif operation == "INSET":
                thickness = op_params.get("thickness", 0.05)
                depth = op_params.get("depth", 0.0)
                bpy.ops.mesh.inset(thickness=thickness, depth=depth)

            elif operation == "BEVEL":
                offset = op_params.get("offset", 0.05)
                segments = op_params.get("segments", 1)
                bpy.ops.mesh.bevel(offset=offset, segments=segments, affect="EDGES")

            elif operation == "LOOP_CUT":
                cuts = op_params.get("cuts", 1)
                edge_index = op_params.get("edge_index", 0)
                # Use bmesh subdivide_edges instead of modal loopcut_slide
                # (loopcut_slide requires viewport interaction and fails headless)
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.edges.ensure_lookup_table()
                    if len(bm.edges) == 0:
                        # Don't call bm.free() here — the finally block handles it
                        _exit_edit_mode()
                        return error_response(
                            "LOOP_CUT failed: mesh has no edges."
                        )
                    if edge_index < 0 or edge_index >= len(bm.edges):
                        edge_index = 0
                    # Collect the full edge loop through the start edge
                    loop_edges = _bmesh_collect_edge_loop(bm, bm.edges[edge_index])
                    if loop_edges:
                        bmesh.ops.subdivide_edges(
                            bm,
                            edges=loop_edges,
                            cuts=cuts,
                            use_grid_fill=True,
                        )
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            elif operation == "SUBDIVIDE":
                cuts = op_params.get("cuts", 1)
                bpy.ops.mesh.subdivide(number_cuts=cuts)

            elif operation == "DISSOLVE":
                angle = math.radians(op_params.get("angle", 5.0))
                bpy.ops.mesh.dissolve_limited(angle_limit=angle)

            elif operation == "MOVE":
                from mathutils import Vector
                value = op_params.get("value")
                if not value or not isinstance(value, (list, tuple)) or len(value) != 3:
                    _exit_edit_mode()
                    return error_response(
                        "MOVE requires 'value' as a JSON array of 3 numbers [x, y, z]."
                    )
                offset = Vector(value)
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    selected_verts = [v for v in bm.verts if v.select]
                    if not selected_verts:
                        _exit_edit_mode()
                        return error_response(
                            "No vertices selected. Select vertices before using MOVE."
                        )
                    for v in selected_verts:
                        v.co += offset
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            else:
                _exit_edit_mode()
                return error_response(
                    f"Unknown operation '{operation}'. "
                    "Valid: EXTRUDE, INSET, BEVEL, LOOP_CUT, SUBDIVIDE, DISSOLVE, MOVE."
                )

        _exit_edit_mode()
        mesh_after = len(obj.data.vertices)

        return ok_response({
            "object_name": obj.name,
            "operation": operation,
            "vertices_before": mesh_before,
            "vertices_after": mesh_after,
        })

    except Exception as e:
        return error_response(f"Mesh edit operation '{operation}' failed: {e}")
    finally:
        try:
            _exit_edit_mode()
        except Exception:
            pass


def _handle_mesh_select(params):
    """
    Select mesh elements in Edit Mode.
    Route: POST /api/mesh/select
    """
    object_name = params.get("object_name")
    mode = params.get("mode", "").upper()
    sel_params = params.get("parameters") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not mode:
        return error_response("Parameter 'mode' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)
        selected_count = 0

        with temp_override("VIEW_3D"):
            if mode == "ALL":
                bpy.ops.mesh.select_all(action="SELECT")
                # Count selected faces after select-all
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.faces.ensure_lookup_table()
                    selected_count = sum(1 for f in bm.faces if f.select)
                finally:
                    bm.free()

            elif mode == "NONE":
                bpy.ops.mesh.select_all(action="DESELECT")

            elif mode in ("FACE_INDEX", "VERT_INDEX", "EDGE_INDEX"):
                indices = sel_params.get("indices", [])
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bpy.ops.mesh.select_all(action="DESELECT")

                    if mode == "FACE_INDEX":
                        bm.faces.ensure_lookup_table()
                        for idx in indices:
                            if 0 <= idx < len(bm.faces):
                                bm.faces[idx].select = True
                                selected_count += 1
                    elif mode == "VERT_INDEX":
                        bm.verts.ensure_lookup_table()
                        for idx in indices:
                            if 0 <= idx < len(bm.verts):
                                bm.verts[idx].select = True
                                selected_count += 1
                    elif mode == "EDGE_INDEX":
                        bm.edges.ensure_lookup_table()
                        for idx in indices:
                            if 0 <= idx < len(bm.edges):
                                bm.edges[idx].select = True
                                selected_count += 1

                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            elif mode == "TOP":
                threshold = sel_params.get("threshold", 0.9)
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.faces.ensure_lookup_table()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    for face in bm.faces:
                        if face.normal.z > threshold:
                            face.select = True
                            selected_count += 1
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            elif mode == "BOTTOM":
                threshold = sel_params.get("threshold", 0.9)
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.faces.ensure_lookup_table()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    for face in bm.faces:
                        if face.normal.z < -threshold:
                            face.select = True
                            selected_count += 1
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            elif mode == "LOOP":
                edge_index = sel_params.get("edge_index", 0)
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.edges.ensure_lookup_table()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    if 0 <= edge_index < len(bm.edges):
                        bm.edges[edge_index].select = True
                        bmesh.update_edit_mesh(obj.data)
                        bpy.ops.mesh.loop_select(extend=True)
                finally:
                    bm.free()

            elif mode == "LINKED":
                bpy.ops.mesh.select_linked()

            elif mode == "BY_NORMAL":
                direction = sel_params.get("direction", [0, 0, 1])
                threshold = sel_params.get("threshold", 0.1)
                from mathutils import Vector
                target_normal = Vector(direction).normalized()
                bm = bmesh.from_edit_mesh(obj.data)
                try:
                    bm.faces.ensure_lookup_table()
                    bpy.ops.mesh.select_all(action="DESELECT")
                    for face in bm.faces:
                        if face.normal.dot(target_normal) >= (1.0 - threshold):
                            face.select = True
                            selected_count += 1
                    bmesh.update_edit_mesh(obj.data)
                finally:
                    bm.free()

            else:
                _exit_edit_mode()
                return error_response(
                    f"Unknown select mode '{mode}'. "
                    "Valid: ALL, NONE, FACE_INDEX, VERT_INDEX, EDGE_INDEX, "
                    "TOP, BOTTOM, LOOP, LINKED, BY_NORMAL."
                )

        # Stay in Edit Mode — selection is only meaningful there
        return ok_response({
            "object_name": obj.name,
            "mode": mode,
            "selected_count": selected_count,
        })

    except Exception as e:
        try:
            _exit_edit_mode()
        except Exception:
            pass
        return error_response(f"Mesh select '{mode}' failed: {e}")


def _handle_mesh_separate(params):
    """
    Separate mesh parts into individual objects.
    Route: POST /api/mesh/separate
    """
    object_name = params.get("object_name")
    mode = params.get("mode", "LOOSE").upper()

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    valid_modes = ("SELECTED", "MATERIAL", "LOOSE")
    if mode not in valid_modes:
        return error_response(
            f"Unknown separate mode '{mode}'. Valid: {', '.join(valid_modes)}."
        )

    # Record object names before separation
    objects_before = set(o.name for o in bpy.data.objects)

    try:
        _enter_edit_mode(obj)
        # For SELECTED mode, ensure something is selected
        if mode == "SELECTED":
            bpy.ops.mesh.select_all(action="SELECT")

        with temp_override("VIEW_3D"):
            bpy.ops.mesh.separate(type=mode)

        _exit_edit_mode()

        objects_after = set(o.name for o in bpy.data.objects)
        new_objects = sorted(objects_after - objects_before)
        # Include the original if it still exists
        all_results = sorted(
            ([object_name] if object_name in objects_after else []) + new_objects
        )

        return ok_response({
            "original_object": object_name,
            "mode": mode,
            "result_objects": all_results,
            "new_objects": new_objects,
        })

    except Exception as e:
        return error_response(f"Mesh separate (mode={mode}) failed: {e}")
    finally:
        try:
            _exit_edit_mode()
        except Exception:
            pass


def _handle_mesh_merge(params):
    """
    Merge vertices on a mesh object.
    Route: POST /api/mesh/merge
    """
    object_name = params.get("object_name")
    mode = params.get("mode", "BY_DISTANCE").upper()
    threshold = params.get("threshold", 0.0001)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    valid_modes = ("BY_DISTANCE", "CENTER", "CURSOR", "COLLAPSE")
    if mode not in valid_modes:
        return error_response(
            f"Unknown merge mode '{mode}'. Valid: {', '.join(valid_modes)}."
        )

    try:
        _enter_edit_mode(obj)
        verts_before = len(obj.data.vertices)

        # Select all to operate on the full mesh
        bpy.ops.mesh.select_all(action="SELECT")

        with temp_override("VIEW_3D"):
            if mode == "BY_DISTANCE":
                merge_vertices(threshold=threshold)
            else:
                bpy.ops.mesh.merge(type=mode)

        _exit_edit_mode()

        verts_after = len(obj.data.vertices)
        removed = verts_before - verts_after

        return ok_response({
            "object_name": obj.name,
            "mode": mode,
            "vertices_before": verts_before,
            "vertices_after": verts_after,
            "vertices_removed": removed,
        })

    except Exception as e:
        return error_response(f"Mesh merge (mode={mode}) failed: {e}")
    finally:
        try:
            _exit_edit_mode()
        except Exception:
            pass


def _handle_mesh_normals(params):
    """
    Perform normals operations on a mesh object.
    Route: POST /api/mesh/normals
    """
    object_name = params.get("object_name")
    mode = params.get("mode", "").upper()
    auto_smooth_angle = params.get("auto_smooth_angle", 30.0)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not mode:
        return error_response("Parameter 'mode' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    valid_modes = ("SMOOTH", "FLAT", "AUTO_SMOOTH", "RECALCULATE", "FLIP")
    if mode not in valid_modes:
        return error_response(
            f"Unknown normals mode '{mode}'. Valid: {', '.join(valid_modes)}."
        )

    try:
        ensure_context_for_object(obj)

        if mode == "SMOOTH":
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(bpy.ops.object.shade_smooth)
            if not ok:
                return error_response(f"shade_smooth failed: {res}")

        elif mode == "FLAT":
            with temp_override("VIEW_3D"):
                ok, res = safe_operator_call(bpy.ops.object.shade_flat)
            if not ok:
                return error_response(f"shade_flat failed: {res}")

        elif mode == "AUTO_SMOOTH":
            angle_rad = math.radians(auto_smooth_angle)
            method = get_auto_smooth_method()
            if method == "property":
                # Blender 3.x
                obj.data.use_auto_smooth = True
                obj.data.auto_smooth_angle = angle_rad
                with temp_override("VIEW_3D"):
                    safe_operator_call(bpy.ops.object.shade_smooth)
            else:
                # Blender 4.x
                with temp_override("VIEW_3D"):
                    ok, res = safe_operator_call(
                        bpy.ops.object.shade_smooth,
                        use_auto_smooth=True,
                        auto_smooth_angle=angle_rad,
                    )
                if not ok:
                    try:
                        bpy.ops.object.shade_smooth_by_angle(angle=angle_rad)
                    except (RuntimeError, AttributeError) as fallback_err:
                        return error_response(
                            f"AUTO_SMOOTH failed on Blender 4.x: {fallback_err}"
                        )

        elif mode == "RECALCULATE":
            try:
                _enter_edit_mode(obj)
                bpy.ops.mesh.select_all(action="SELECT")
                with temp_override("VIEW_3D"):
                    bpy.ops.mesh.normals_make_consistent(inside=False)
            finally:
                _exit_edit_mode()

        elif mode == "FLIP":
            try:
                _enter_edit_mode(obj)
                bpy.ops.mesh.select_all(action="SELECT")
                with temp_override("VIEW_3D"):
                    bpy.ops.mesh.flip_normals()
            finally:
                _exit_edit_mode()

        return ok_response({
            "object_name": obj.name,
            "mode": mode,
            "auto_smooth_angle": auto_smooth_angle if mode == "AUTO_SMOOTH" else None,
        })

    except Exception as e:
        return error_response(f"Mesh normals (mode={mode}) failed: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_boolean_operation(params):
    """
    Perform a Boolean operation between two mesh objects.
    Route: POST /api/mesh/boolean
    """
    object_name = params.get("object_name")
    cutter_name = params.get("cutter")
    operation = params.get("operation", "").upper()
    apply = params.get("apply", True)
    remove_cutter = params.get("remove_cutter", True)

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not cutter_name:
        return error_response("Parameter 'cutter' is required.")
    if not operation:
        return error_response("Parameter 'operation' is required.")

    valid_ops = ("DIFFERENCE", "UNION", "INTERSECT")
    if operation not in valid_ops:
        return error_response(
            f"Unknown operation '{operation}'. Valid: {', '.join(valid_ops)}."
        )

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    cutter_obj, err = _get_mesh_object(cutter_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)

        # Add Boolean modifier
        mod = obj.modifiers.new("Boolean", "BOOLEAN")
        mod.operation = operation
        mod.object = cutter_obj

        if apply:
            with temp_override("VIEW_3D"):
                bpy.ops.object.modifier_apply(modifier=mod.name)

            if remove_cutter:
                bpy.data.objects.remove(cutter_obj, do_unlink=True)

        mesh = obj.data
        result = {
            "object_name": obj.name,
            "operation": operation,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.polygons),
        }

        if not apply and remove_cutter:
            result["warning"] = ("remove_cutter ignored because apply=false — "
                                 "the Boolean modifier still references the cutter object. "
                                 "Set apply=true (default) to enable cutter removal.")
            result["cutter_kept"] = cutter_obj.name

        return ok_response(result)

    except Exception as e:
        return error_response(f"Boolean operation '{operation}' failed: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("mesh", "from-data", _handle_mesh_from_data)
register_handler("mesh", "edit", _handle_mesh_edit)
register_handler("mesh", "select", _handle_mesh_select)
register_handler("mesh", "separate", _handle_mesh_separate)
register_handler("mesh", "merge", _handle_mesh_merge)
register_handler("mesh", "normals", _handle_mesh_normals)
register_handler("mesh", "boolean", _handle_boolean_operation)
