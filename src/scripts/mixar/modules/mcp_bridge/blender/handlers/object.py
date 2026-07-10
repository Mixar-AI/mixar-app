"""
Object handlers for Blender MCP Bridge.
Provides object-level operations: list, info, create, delete,
transform, duplicate, select, join.
"""

import bpy
from mathutils import Vector, Euler
from ..utils.response import ok_response, error_response, not_found
from ..utils.context_helpers import temp_override, safe_operator_call
from . import register_handler

# Mapping from user-facing type names to bpy.ops.mesh.primitive_* operator calls.
# Key: uppercase type string; Value: callable that adds the primitive.
_MESH_PRIMITIVE_OPS = {
    "CUBE":     lambda: bpy.ops.mesh.primitive_cube_add(),
    "SPHERE":   lambda: bpy.ops.mesh.primitive_uv_sphere_add(),
    "CYLINDER": lambda: bpy.ops.mesh.primitive_cylinder_add(),
    "PLANE":    lambda: bpy.ops.mesh.primitive_plane_add(),
    "CONE":     lambda: bpy.ops.mesh.primitive_cone_add(),
    "TORUS":    lambda: bpy.ops.mesh.primitive_torus_add(),
    "CIRCLE":   lambda: bpy.ops.mesh.primitive_circle_add(),
    "GRID":     lambda: bpy.ops.mesh.primitive_grid_add(),
    "MONKEY":   lambda: bpy.ops.mesh.primitive_monkey_add(),
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _obj_location(obj):
    return list(obj.location)


def _obj_rotation(obj):
    return list(obj.rotation_euler)


def _obj_scale(obj):
    return list(obj.scale)


# ─── Handlers ───────────────────────────────────────────────────────────────

def _handle_object_list(params):
    """
    List objects in the active scene, optionally filtered by type.
    Supports pagination via limit/offset to avoid huge payloads in large scenes.

    Route: POST /api/object/list

    Params:
        type (str, optional): Filter by object type (MESH, LIGHT, CAMERA, etc).
        limit (int, optional): Max number of objects to return. Default 500.
        offset (int, optional): Number of objects to skip. Default 0.

    Returns:
        {objects: [{name, type, location, visible}], total_count, limit, offset}
    """
    try:
        type_filter = params.get("type", "").upper() if params.get("type") else None
        limit = min(int(params.get("limit", 500)), 5000)
        offset = max(int(params.get("offset", 0)), 0)

        # Collect all matching objects first for accurate total_count
        all_matching = []
        for obj in bpy.data.objects:
            if type_filter and obj.type != type_filter:
                continue
            all_matching.append(obj)

        total_count = len(all_matching)

        # Apply pagination
        page = all_matching[offset:offset + limit]
        objects = []
        for obj in page:
            objects.append({
                "name": obj.name,
                "object_name": obj.name,
                "type": obj.type,
                "location": _obj_location(obj),
                "visible": not obj.hide_viewport,
            })

        return ok_response({
            "objects": objects,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return error_response(f"Failed to list objects: {e}")


def _handle_object_info(params):
    """
    Get detailed information about a specific object.

    Route: POST /api/object/info

    Params:
        name (str): The object name.

    Returns:
        name, type, location, rotation_euler, scale, dimensions, parent,
        collections, modifiers, materials, mesh_stats (for MESH objects),
        world_bounds (min/max/center in world space).
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    try:
        obj = bpy.data.objects.get(name)
        if obj is None:
            return not_found(name)

        info = {
            "name": obj.name,
            "object_name": obj.name,
            "type": obj.type,
            "location": _obj_location(obj),
            "rotation_euler": _obj_rotation(obj),
            "scale": _obj_scale(obj),
            "dimensions": list(obj.dimensions),
            "parent": obj.parent.name if obj.parent else None,
            "collections": [col.name for col in obj.users_collection],
            "modifiers": [mod.name for mod in obj.modifiers],
            "materials": [
                mat.name if mat else None
                for mat in obj.material_slots
            ],
        }

        # Mesh statistics
        if obj.type == "MESH" and obj.data:
            mesh = obj.data
            info["mesh_stats"] = {
                "vertex_count": len(mesh.vertices),
                "edge_count": len(mesh.edges),
                "face_count": len(mesh.polygons),
            }

        # World-space bounding box for precise assembly
        if hasattr(obj, 'bound_box') and obj.bound_box:
            world_bb = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            xs = [v.x for v in world_bb]
            ys = [v.y for v in world_bb]
            zs = [v.z for v in world_bb]
            info["world_bounds"] = {
                "min": [round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)],
                "max": [round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)],
                "center": [round((min(xs)+max(xs))/2, 6), round((min(ys)+max(ys))/2, 6), round((min(zs)+max(zs))/2, 6)],
            }

        return ok_response(info)
    except Exception as e:
        return error_response(f"Failed to get object info: {e}")


def _handle_object_create(params):
    """
    Create a new object (mesh primitive or empty) in the active scene.

    Route: POST /api/object/create

    Params:
        type (str): CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS, EMPTY, etc.
        name (str, optional): Desired name for the new object.
        location ([x,y,z], optional): World-space location.
        rotation ([x,y,z], optional): Euler rotation in radians.
        scale ([x,y,z], optional): Scale factors.

    Returns:
        {name, type, location}
    """
    obj_type = (params.get("type") or "").upper()
    if not obj_type:
        return error_response("Parameter 'type' is required.")

    name = params.get("name")
    location = params.get("location", [0.0, 0.0, 0.0])
    rotation = params.get("rotation", [0.0, 0.0, 0.0])
    scale = params.get("scale", [1.0, 1.0, 1.0])

    try:
        if obj_type == "EMPTY":
            # Create an Empty directly via bpy.data — no operator needed.
            mesh_name = name if name else "Empty"
            obj = bpy.data.objects.new(mesh_name, None)
            bpy.context.scene.collection.objects.link(obj)
        elif obj_type in _MESH_PRIMITIVE_OPS:
            # Use the viewport context so primitive ops work correctly.
            with temp_override("VIEW_3D"):
                # Deselect all first so we can identify the new object.
                bpy.ops.object.select_all(action="DESELECT")
                _MESH_PRIMITIVE_OPS[obj_type]()

            # The newly created object is now active.
            obj = bpy.context.active_object
            if obj is None:
                return error_response(f"Object creation succeeded but active object is None.")
        else:
            return error_response(
                f"Unknown object type '{obj_type}'. "
                f"Supported types: {', '.join(sorted(_MESH_PRIMITIVE_OPS.keys()) + ['EMPTY'])}"
            )

        # Apply transform.
        obj.location = Vector(location)
        obj.rotation_euler = Euler(rotation)
        obj.scale = Vector(scale)

        # Rename if requested.
        if name:
            obj.name = name
            if obj.data:
                obj.data.name = name

        return ok_response({
            "name": obj.name,
            "object_name": obj.name,
            "type": obj.type,
            "location": _obj_location(obj),
        })
    except Exception as e:
        return error_response(f"Failed to create object: {e}")


def _handle_object_delete(params):
    """
    Delete one or more objects from the scene.

    Route: POST /api/object/delete

    Params:
        name (str, optional): Single object name.
        names ([str], optional): Array of object names.

    Returns:
        {deleted_count: int, deleted_names: [str]}
    """
    # Collect target names.
    target_names = []
    if params.get("names"):
        target_names.extend(params["names"])
    if params.get("name"):
        n = params["name"]
        if n not in target_names:
            target_names.append(n)

    if not target_names:
        return error_response("Provide 'name' or 'names' to delete.")

    try:
        deleted = []
        not_found_names = []

        for name in target_names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                not_found_names.append(name)
                continue
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(name)

        if not_found_names:
            if deleted:
                return ok_response({
                    "deleted_count": len(deleted),
                    "deleted_names": deleted,
                    "not_found": not_found_names,
                    "warning": f"Partial delete: {len(deleted)} of {len(target_names)} objects deleted",
                })
            return not_found(", ".join(not_found_names))

        return ok_response({"deleted_count": len(deleted), "deleted_names": deleted})
    except Exception as e:
        return error_response(f"Failed to delete objects: {e}")


def _handle_object_transform(params):
    """
    Set location, rotation, and/or scale of an existing object.

    Route: POST /api/object/transform

    Params:
        name (str): Object name.
        location ([x,y,z], optional): New world-space location.
        rotation ([x,y,z], optional): New Euler rotation in radians.
        scale ([x,y,z], optional): New scale factors.

    Returns:
        {name, location, rotation, scale}
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    try:
        obj = bpy.data.objects.get(name)
        if obj is None:
            return not_found(name)

        if "location" in params:
            obj.location = Vector(params["location"])
        if "rotation" in params:
            obj.rotation_euler = Euler(params["rotation"])
        if "scale" in params:
            obj.scale = Vector(params["scale"])

        return ok_response({
            "name": obj.name,
            "object_name": obj.name,
            "location": _obj_location(obj),
            "rotation": _obj_rotation(obj),
            "scale": _obj_scale(obj),
        })
    except Exception as e:
        return error_response(f"Failed to transform object: {e}")


def _handle_object_duplicate(params):
    """
    Duplicate an object. Creates a full copy by default; linked=true shares mesh data.

    Route: POST /api/object/duplicate

    Params:
        name (str): Source object name.
        new_name (str, optional): Name for the duplicate.
        linked (bool, optional): Share mesh data with original. Defaults to False.

    Returns:
        {name, original, linked}
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    new_name = params.get("new_name")
    linked = bool(params.get("linked", False))

    try:
        src = bpy.data.objects.get(name)
        if src is None:
            return not_found(name)

        # Copy the object (always copies the object datablock).
        new_obj = src.copy()

        # Copy mesh data unless linked duplicate is requested.
        if not linked and src.data is not None:
            new_obj.data = src.data.copy()

        # Apply name if provided.
        if new_name:
            new_obj.name = new_name
            if new_obj.data:
                new_obj.data.name = new_name

        # Link into the same collections as the source.
        for col in src.users_collection:
            col.objects.link(new_obj)

        return ok_response({
            "name": new_obj.name,
            "object_name": new_obj.name,
            "original": src.name,
            "linked": linked,
        })
    except Exception as e:
        return error_response(f"Failed to duplicate object: {e}")


def _handle_object_select(params):
    """
    Select or deselect objects using SET, ADD, REMOVE, or TOGGLE mode.

    Route: POST /api/object/select

    Params:
        names ([str]): Object names to act on.
        mode (str, optional): SET | ADD | REMOVE | TOGGLE. Defaults to SET.
        active (str, optional): Object to set as the active object.

    Returns:
        {selected: [names], active: name}
    """
    names = params.get("names")
    if names is None:
        return error_response("Parameter 'names' is required.")

    mode = (params.get("mode") or "SET").upper()
    active_name = params.get("active")

    valid_modes = {"SET", "ADD", "REMOVE", "TOGGLE"}
    if mode not in valid_modes:
        return error_response(f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(valid_modes))}.")

    try:
        view_layer = bpy.context.view_layer

        # For SET mode, deselect everything first.
        if mode == "SET":
            for obj in bpy.data.objects:
                obj.select_set(False)

        selected = []
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue  # Silently skip missing objects.

            if mode in ("SET", "ADD"):
                obj.select_set(True)
            elif mode == "REMOVE":
                obj.select_set(False)
            elif mode == "TOGGLE":
                obj.select_set(not obj.select_get())

            if obj.select_get():
                selected.append(obj.name)

        # Set active object.
        active_obj = None
        if active_name:
            active_obj = bpy.data.objects.get(active_name)
            if active_obj:
                view_layer.objects.active = active_obj
        elif mode in ("SET", "ADD") and names:
            # Default: make the first valid object active.
            first = bpy.data.objects.get(names[0])
            if first:
                view_layer.objects.active = first
                if active_obj is None:
                    active_obj = first

        current_active = view_layer.objects.active

        return ok_response({
            "selected": selected,
            "active": current_active.name if current_active else None,
        })
    except Exception as e:
        return error_response(f"Failed to select objects: {e}")


def _handle_object_join(params):
    """
    Join multiple mesh objects into a single object.

    Route: POST /api/object/join

    Params:
        names ([str]): Array of object names to join (at least 2).
        target_name (str, optional): Name of the object that others merge into.
            Defaults to the first name in the array.

    Returns:
        {object_name, name, vertex_count, face_count, material_count, joined_count}
    """
    names = params.get("names", [])
    if not names or not isinstance(names, list) or len(names) < 2:
        return error_response("'names' must be a list of at least 2 object names")

    target_name = params.get("target_name", names[0])

    # Validate all objects exist and are MESH type
    objects = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if not obj:
            return error_response(f"Object '{name}' not found")
        if obj.type != 'MESH':
            return error_response(f"Object '{name}' is type '{obj.type}', not MESH. Only mesh objects can be joined.")
        objects.append(obj)

    target = bpy.data.objects.get(target_name)
    if not target:
        return error_response(f"Target object '{target_name}' not found")
    if target not in objects:
        return error_response(f"Target '{target_name}' must be in the names list")

    try:
        # Deselect all, select targets, set active
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = target

        # Join using temp_override
        with temp_override("VIEW_3D"):
            bpy.ops.object.join()

        # Get result info
        merged = bpy.context.active_object
        mesh = merged.data

        return ok_response({
            "object_name": merged.name,
            "name": merged.name,
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.polygons),
            "material_count": len(mesh.materials),
            "joined_count": len(names),
        })
    except Exception as e:
        return error_response(f"Failed to join objects: {e}")


def _handle_object_set_parent(params):
    """
    Set or clear an object's parent.

    Route: POST /api/object/set-parent

    Params:
        child (str): Name of the child object.
        parent (str): Name of the parent object. Empty string to clear parent.
        keep_transform (bool, optional): If true, child keeps its world transform. Default: True.

    Returns:
        {object_name, name, parent, world_location}
    """
    child_name = params.get("child")
    parent_name = params.get("parent")
    keep_transform = params.get("keep_transform", True)

    if not child_name:
        return error_response("'child' parameter is required")

    try:
        child_obj = bpy.data.objects.get(child_name)
        if not child_obj:
            return error_response(f"Child object '{child_name}' not found")

        # Unparent case
        if not parent_name or parent_name == "":
            if keep_transform:
                # Store world matrix before clearing parent
                world_matrix = child_obj.matrix_world.copy()
            child_obj.parent = None
            if keep_transform:
                child_obj.matrix_world = world_matrix
            loc = child_obj.matrix_world.translation
            return ok_response({
                "object_name": child_obj.name,
                "name": child_obj.name,
                "parent": None,
                "world_location": [round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)],
            })

        # Set parent case
        parent_obj = bpy.data.objects.get(parent_name)
        if not parent_obj:
            return error_response(f"Parent object '{parent_name}' not found")

        child_obj.parent = parent_obj
        if keep_transform:
            child_obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()

        loc = child_obj.matrix_world.translation
        return ok_response({
            "object_name": child_obj.name,
            "name": child_obj.name,
            "parent": parent_obj.name,
            "world_location": [round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)],
        })
    except Exception as e:
        return error_response(f"Failed to set parent: {e}")


def _handle_object_apply_transforms(params):
    """
    Apply (freeze) an object's location, rotation, and/or scale so the
    transform values reset to identity while the mesh keeps its current shape.

    Route: POST /api/object/apply-transforms

    Params:
        name (str): The object name (also accepts 'object_name' for backward compat).
        location (bool, optional): Apply location. Default True.
        rotation (bool, optional): Apply rotation. Default True.
        scale (bool, optional): Apply scale. Default True.

    Returns:
        {object_name, applied: {location, rotation, scale}, location, rotation, scale}
    """
    object_name = params.get("name") or params.get("object_name")
    if not object_name:
        return error_response("Parameter 'name' is required.")

    try:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        loc = bool(params.get("location", True))
        rot = bool(params.get("rotation", True))
        scl = bool(params.get("scale", True))

        # Select and activate the target object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        with temp_override("VIEW_3D"):
            bpy.ops.object.transform_apply(location=loc, rotation=rot, scale=scl)

        return ok_response({
            "object_name": obj.name,
            "applied": {
                "location": loc,
                "rotation": rot,
                "scale": scl,
            },
            "location": _obj_location(obj),
            "rotation": _obj_rotation(obj),
            "scale": _obj_scale(obj),
        })
    except Exception as e:
        return error_response(f"Failed to apply transforms: {e}")


# ─── Register routes ───
register_handler("object", "list", _handle_object_list)
register_handler("object", "info", _handle_object_info)
register_handler("object", "create", _handle_object_create)
register_handler("object", "delete", _handle_object_delete)
register_handler("object", "transform", _handle_object_transform)
register_handler("object", "duplicate", _handle_object_duplicate)
register_handler("object", "select", _handle_object_select)
register_handler("object", "join", _handle_object_join)
register_handler("object", "set-parent", _handle_object_set_parent)
register_handler("object", "apply-transforms", _handle_object_apply_transforms)
