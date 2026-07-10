"""
Advanced armature handlers for Blender MCP Bridge.
Provides: armature/create, armature/add-bone, armature/edit-bone, armature/delete-bone,
          armature/parent-to-mesh, armature/list-bones, armature/set-bone-constraint,
          armature/remove-constraint, armature/set-ik, armature/auto-rig,
          armature/weight-paint-auto, armature/weight-paint-normalize,
          armature/weight-assign, armature/pose-bone, armature/pose-reset,
          armature/symmetrize, armature/bone-layers, armature/rename-bones
"""

import math
import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from ...utils.compat import is_blender_4
from .. import register_handler


# ─── Armature-specific helpers ──────────────────────────────────────────────────

def _get_armature_object(name):
    """Return (obj, None) or (None, error_response) for an ARMATURE object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Armature")
    if obj.type != "ARMATURE":
        return None, error_response(
            f"Object '{name}' is type '{obj.type}', not 'ARMATURE'."
        )
    return obj, None


def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Mesh object")
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _enter_edit_mode(obj):
    """Ensure armature is active and in Edit Mode."""
    ensure_context_for_object(obj)
    if bpy.context.mode != "EDIT_ARMATURE":
        bpy.ops.object.mode_set(mode="EDIT")


def _enter_pose_mode(obj):
    """Ensure armature is active and in Pose Mode."""
    ensure_context_for_object(obj)
    if bpy.context.mode != "POSE":
        bpy.ops.object.mode_set(mode="POSE")


def _exit_to_object_mode():
    """Switch back to Object Mode."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_armature_create(params):
    """
    Create a new armature object.
    Route: armature/create
    """
    try:
        name = params.get("name")
        if not name:
            return error_response("Parameter 'name' is required.")
        location = params.get("location", [0.0, 0.0, 0.0])

        armature_data = bpy.data.armatures.new(name)
        obj = bpy.data.objects.new(name, armature_data)
        bpy.context.collection.objects.link(obj)
        obj.location = tuple(location)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "armature_name": obj.name,
            "location": [round(v, 6) for v in obj.location],
        })
    except Exception as e:
        return error_response(f"Failed to create armature: {e}")


def _handle_armature_add_bone(params):
    """
    Add a bone to an armature.
    Route: armature/add-bone
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    head = params.get("head")
    tail = params.get("tail")
    parent_bone_name = params.get("parent_bone")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")
    if head is None or len(head) != 3:
        return error_response("Parameter 'head' must be a [x, y, z] array.")
    if tail is None or len(tail) != 3:
        return error_response("Parameter 'tail' must be a [x, y, z] array.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)

        edit_bone = obj.data.edit_bones.new(bone_name)
        edit_bone.head = tuple(head)
        edit_bone.tail = tuple(tail)

        if parent_bone_name:
            parent = obj.data.edit_bones.get(parent_bone_name)
            if parent is None:
                _exit_to_object_mode()
                return error_response(
                    f"Parent bone '{parent_bone_name}' not found in armature '{armature_name}'."
                )
            edit_bone.parent = parent

        actual_name = edit_bone.name  # Blender may suffix for uniqueness

        return ok_response({
            "armature_name": armature_name,
            "bone_name": actual_name,
            "head": list(head),
            "tail": list(tail),
            "parent_bone": parent_bone_name,
        })
    except Exception as e:
        return error_response(f"Failed to add bone: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_edit_bone(params):
    """
    Modify properties of an existing bone.
    Route: armature/edit-bone
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)

        edit_bone = obj.data.edit_bones.get(bone_name)
        if edit_bone is None:
            return error_response(
                f"Bone '{bone_name}' not found in armature '{armature_name}'."
            )

        updated = {}

        head = params.get("head")
        if head is not None:
            edit_bone.head = tuple(head)
            updated["head"] = list(head)

        tail = params.get("tail")
        if tail is not None:
            edit_bone.tail = tuple(tail)
            updated["tail"] = list(tail)

        roll = params.get("roll")
        if roll is not None:
            edit_bone.roll = math.radians(roll)
            updated["roll"] = roll

        connected = params.get("connected")
        if connected is not None:
            edit_bone.use_connect = bool(connected)
            updated["connected"] = bool(connected)

        return ok_response({
            "armature_name": armature_name,
            "bone_name": bone_name,
            "updated": updated,
        })
    except Exception as e:
        return error_response(f"Failed to edit bone: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_delete_bone(params):
    """
    Delete a bone from an armature.
    Route: armature/delete-bone
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)

        edit_bone = obj.data.edit_bones.get(bone_name)
        if edit_bone is None:
            return error_response(
                f"Bone '{bone_name}' not found in armature '{armature_name}'."
            )

        obj.data.edit_bones.remove(edit_bone)

        return ok_response({
            "armature_name": armature_name,
            "deleted_bone": bone_name,
        })
    except Exception as e:
        return error_response(f"Failed to delete bone: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_parent_to_mesh(params):
    """
    Parent a mesh to an armature with the given weighting method.
    Route: armature/parent-to-mesh
    """
    armature_name = params.get("armature_name")
    mesh_name = params.get("mesh_name")
    method = params.get("method", "AUTO").upper()

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not mesh_name:
        return error_response("Parameter 'mesh_name' is required.")

    method_map = {
        "AUTO": "ARMATURE_AUTO",
        "EMPTY": "ARMATURE_NAME",
        "ENVELOPE": "ARMATURE_ENVELOPE",
    }
    blender_method = method_map.get(method)
    if blender_method is None:
        return error_response(
            f"Unknown method '{method}'. Valid: AUTO, EMPTY, ENVELOPE."
        )

    arm_obj, err = _get_armature_object(armature_name)
    if err:
        return err

    mesh_obj, err = _get_mesh_object(mesh_name)
    if err:
        return err

    try:
        # Ensure OBJECT mode before selection
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        mesh_obj.select_set(True)
        arm_obj.select_set(True)
        bpy.context.view_layer.objects.active = arm_obj

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.parent_set, type=blender_method
            )

        if not ok:
            return error_response(f"parent_set failed: {res}")

        return ok_response({
            "armature_name": armature_name,
            "mesh_name": mesh_name,
            "method": method,
        })
    except Exception as e:
        return error_response(f"Failed to parent mesh to armature: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_armature_list_bones(params):
    """
    List all bones in an armature with their properties.
    Route: armature/list-bones
    """
    armature_name = params.get("armature_name")
    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        bones_data = []
        for bone in obj.data.bones:
            bones_data.append({
                "name": bone.name,
                "head": [round(v, 6) for v in bone.head_local],
                "tail": [round(v, 6) for v in bone.tail_local],
                "parent": bone.parent.name if bone.parent else None,
                "length": round(bone.length, 6),
                "connected": bone.use_connect,
            })

        return ok_response({
            "armature_name": armature_name,
            "bone_count": len(bones_data),
            "bones": bones_data,
        })
    except Exception as e:
        return error_response(f"Failed to list bones: {e}")


def _handle_armature_set_bone_constraint(params):
    """
    Add a constraint to a pose bone.
    Route: armature/set-bone-constraint
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    constraint_type = params.get("constraint_type")
    constraint_params = params.get("params") or {}

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")
    if not constraint_type:
        return error_response("Parameter 'constraint_type' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_pose_mode(obj)

        pose_bone = obj.pose.bones.get(bone_name)
        if pose_bone is None:
            return error_response(
                f"Pose bone '{bone_name}' not found in armature '{armature_name}'."
            )

        constraint = pose_bone.constraints.new(constraint_type)

        # Apply provided parameters to the constraint
        for key, value in constraint_params.items():
            try:
                # Handle target/pole_target specially — convert string to object
                if key in ("target", "pole_target") and isinstance(value, str):
                    target_obj = bpy.data.objects.get(value)
                    if target_obj is not None:
                        setattr(constraint, key, target_obj)
                else:
                    current = getattr(constraint, key, None)
                    if current is not None:
                        value = coerce_value(current, value)
                    setattr(constraint, key, value)
            except (AttributeError, TypeError):
                pass  # Skip unsupported attributes rather than failing

        return ok_response({
            "armature_name": armature_name,
            "bone_name": bone_name,
            "constraint_type": constraint_type,
            "constraint_name": constraint.name,
        })
    except Exception as e:
        return error_response(f"Failed to set bone constraint: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_remove_constraint(params):
    """
    Remove a constraint from a pose bone.
    Route: armature/remove-constraint
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    constraint_name = params.get("constraint_name")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")
    if not constraint_name:
        return error_response("Parameter 'constraint_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_pose_mode(obj)

        pose_bone = obj.pose.bones.get(bone_name)
        if pose_bone is None:
            return error_response(
                f"Pose bone '{bone_name}' not found in armature '{armature_name}'."
            )

        constraint = pose_bone.constraints.get(constraint_name)
        if constraint is None:
            return error_response(
                f"Constraint '{constraint_name}' not found on bone '{bone_name}'."
            )

        pose_bone.constraints.remove(constraint)

        return ok_response({
            "armature_name": armature_name,
            "bone_name": bone_name,
            "removed_constraint": constraint_name,
        })
    except Exception as e:
        return error_response(f"Failed to remove constraint: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_set_ik(params):
    """
    Set up an Inverse Kinematics constraint on a pose bone.
    Route: armature/set-ik
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    chain_length = params.get("chain_length")
    target_name = params.get("target")
    pole_target_name = params.get("pole_target")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")
    if chain_length is None:
        return error_response("Parameter 'chain_length' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_pose_mode(obj)

        pose_bone = obj.pose.bones.get(bone_name)
        if pose_bone is None:
            return error_response(
                f"Pose bone '{bone_name}' not found in armature '{armature_name}'."
            )

        constraint = pose_bone.constraints.new("INVERSE_KINEMATICS")
        constraint.chain_count = int(chain_length)

        resolved_target = None
        if target_name:
            target_obj = bpy.data.objects.get(target_name)
            if target_obj is not None:
                constraint.target = target_obj
                resolved_target = target_obj.name
            else:
                # Don't fail hard — just skip
                resolved_target = None

        resolved_pole = None
        if pole_target_name:
            pole_obj = bpy.data.objects.get(pole_target_name)
            if pole_obj is not None:
                constraint.pole_target = pole_obj
                resolved_pole = pole_obj.name

        return ok_response({
            "armature_name": armature_name,
            "bone_name": bone_name,
            "constraint_name": constraint.name,
            "chain_length": int(chain_length),
            "target": resolved_target,
            "pole_target": resolved_pole,
        })
    except Exception as e:
        return error_response(f"Failed to set IK: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_auto_rig(params):
    """
    Auto-rig a mesh using the Rigify addon.
    Route: armature/auto-rig
    """
    mesh_name = params.get("mesh_name")
    rig_type = params.get("type", "HUMAN").upper()

    if not mesh_name:
        return error_response("Parameter 'mesh_name' is required.")

    mesh_obj, err = _get_mesh_object(mesh_name)
    if err:
        return err

    valid_types = ("HUMAN", "ANIMAL")
    if rig_type not in valid_types:
        return error_response(
            f"Unknown rig type '{rig_type}'. Valid: HUMAN, ANIMAL."
        )

    try:
        # Enable rigify addon
        try:
            bpy.ops.preferences.addon_enable(module="rigify")
        except Exception:
            pass  # May already be enabled

        # Deselect all, then add metarig
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")

        armature_name_before = set(
            o.name for o in bpy.data.objects if o.type == "ARMATURE"
        )

        with temp_override("VIEW_3D"):
            if rig_type == "HUMAN":
                try:
                    bpy.ops.object.armature_human_metarig_add()
                except AttributeError:
                    # Fallback to basic armature if rigify not available
                    bpy.ops.object.armature_add()
            else:
                # ANIMAL — try cat or fall back to basic armature
                try:
                    bpy.ops.object.armature_animal_metarig_add()
                except AttributeError:
                    try:
                        bpy.ops.object.armature_add()
                    except Exception:
                        pass

        # Find newly created armature
        armature_name_after = set(
            o.name for o in bpy.data.objects if o.type == "ARMATURE"
        )
        new_armatures = armature_name_after - armature_name_before

        if not new_armatures:
            return error_response("Rigify metarig creation failed — no armature was added.")

        rig_name = sorted(new_armatures)[0]
        rig_obj = bpy.data.objects[rig_name]

        # Move rig to mesh location
        rig_obj.location = mesh_obj.location.copy()

        # Parent mesh to armature with auto weights
        bpy.ops.object.select_all(action="DESELECT")
        mesh_obj.select_set(True)
        rig_obj.select_set(True)
        bpy.context.view_layer.objects.active = rig_obj

        with temp_override("VIEW_3D"):
            safe_operator_call(bpy.ops.object.parent_set, type="ARMATURE_AUTO")

        return ok_response({
            "mesh_name": mesh_name,
            "rig_type": rig_type,
            "armature_name": rig_name,
        })
    except Exception as e:
        return error_response(f"Auto-rig failed: {e}")


def _handle_armature_weight_paint_auto(params):
    """
    Apply automatic weights from armature to mesh.
    Route: armature/weight-paint-auto
    """
    armature_name = params.get("armature_name")
    mesh_name = params.get("mesh_name")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not mesh_name:
        return error_response("Parameter 'mesh_name' is required.")

    arm_obj, err = _get_armature_object(armature_name)
    if err:
        return err

    mesh_obj, err = _get_mesh_object(mesh_name)
    if err:
        return err

    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        mesh_obj.select_set(True)
        arm_obj.select_set(True)
        bpy.context.view_layer.objects.active = arm_obj

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.parent_set, type="ARMATURE_AUTO"
            )

        if not ok:
            return error_response(f"Automatic weight paint failed: {res}")

        return ok_response({
            "armature_name": armature_name,
            "mesh_name": mesh_name,
        })
    except Exception as e:
        return error_response(f"Failed to apply automatic weights: {e}")
    finally:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


def _handle_armature_weight_paint_normalize(params):
    """
    Normalize all vertex weights on a mesh.
    Route: armature/weight-paint-normalize
    """
    mesh_name = params.get("mesh_name")
    if not mesh_name:
        return error_response("Parameter 'mesh_name' is required.")

    obj, err = _get_mesh_object(mesh_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        if bpy.context.mode != "WEIGHT_PAINT":
            bpy.ops.object.mode_set(mode="WEIGHT_PAINT")

        with temp_override("VIEW_3D"):
            ok, res = safe_operator_call(
                bpy.ops.object.vertex_group_normalize_all
            )

        if not ok:
            return error_response(f"Normalize weights failed: {res}")

        return ok_response({"mesh_name": mesh_name})
    except Exception as e:
        return error_response(f"Failed to normalize weights: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_weight_assign(params):
    """
    Manually assign weights to a vertex group on a mesh.
    Route: armature/weight-assign
    """
    mesh_name = params.get("mesh_name")
    group_name = params.get("group_name")
    vertex_indices = params.get("vertex_indices")
    weight = params.get("weight")

    if not mesh_name:
        return error_response("Parameter 'mesh_name' is required.")
    if not group_name:
        return error_response("Parameter 'group_name' is required.")
    if vertex_indices is None:
        return error_response("Parameter 'vertex_indices' is required.")
    if weight is None:
        return error_response("Parameter 'weight' is required.")

    weight = float(weight)
    if not (0.0 <= weight <= 1.0):
        return error_response("Parameter 'weight' must be between 0.0 and 1.0.")

    obj, err = _get_mesh_object(mesh_name)
    if err:
        return err

    try:
        # Get or create the vertex group
        vgroup = obj.vertex_groups.get(group_name)
        if vgroup is None:
            vgroup = obj.vertex_groups.new(name=group_name)

        indices = [int(i) for i in vertex_indices]
        vgroup.add(indices, weight, "REPLACE")

        return ok_response({
            "mesh_name": mesh_name,
            "group_name": vgroup.name,
            "vertex_count": len(indices),
            "weight": weight,
        })
    except Exception as e:
        return error_response(f"Failed to assign vertex weights: {e}")


def _handle_armature_pose_bone(params):
    """
    Set pose transform on a bone (rotation in degrees, location in pose space).
    Route: armature/pose-bone
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    rotation = params.get("rotation")   # degrees [x, y, z]
    location = params.get("location")   # pose space [x, y, z]

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_pose_mode(obj)

        pose_bone = obj.pose.bones.get(bone_name)
        if pose_bone is None:
            return error_response(
                f"Pose bone '{bone_name}' not found in armature '{armature_name}'."
            )

        applied_rotation = None
        applied_location = None

        if rotation is not None:
            pose_bone.rotation_mode = "XYZ"
            pose_bone.rotation_euler[0] = math.radians(rotation[0])
            pose_bone.rotation_euler[1] = math.radians(rotation[1])
            pose_bone.rotation_euler[2] = math.radians(rotation[2])
            applied_rotation = list(rotation)

        if location is not None:
            pose_bone.location[0] = location[0]
            pose_bone.location[1] = location[1]
            pose_bone.location[2] = location[2]
            applied_location = list(location)

        return ok_response({
            "armature_name": armature_name,
            "bone_name": bone_name,
            "rotation": applied_rotation,
            "location": applied_location,
        })
    except Exception as e:
        return error_response(f"Failed to pose bone: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_pose_reset(params):
    """
    Reset pose bones to rest position.
    Route: armature/pose-reset
    """
    armature_name = params.get("armature_name")
    target_bones = params.get("bones")  # optional list of bone names

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_pose_mode(obj)

        # Deselect all bones first
        for pb in obj.pose.bones:
            pb.bone.select = False

        reset_names = []

        if target_bones:
            # Select only specified bones
            for name in target_bones:
                pb = obj.pose.bones.get(name)
                if pb is not None:
                    pb.bone.select = True
                    reset_names.append(name)
        else:
            # Select all bones
            for pb in obj.pose.bones:
                pb.bone.select = True
                reset_names.append(pb.name)

        with temp_override("VIEW_3D"):
            safe_operator_call(bpy.ops.pose.rot_clear)
            safe_operator_call(bpy.ops.pose.loc_clear)
            safe_operator_call(bpy.ops.pose.scale_clear)

        return ok_response({
            "armature_name": armature_name,
            "bones_reset": reset_names,
            "count": len(reset_names),
        })
    except Exception as e:
        return error_response(f"Failed to reset pose: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_symmetrize(params):
    """
    Symmetrize bones across the armature X axis.
    Route: armature/symmetrize
    """
    armature_name = params.get("armature_name")
    direction = params.get("direction", "LEFT_TO_RIGHT").upper()

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")

    direction_map = {
        "LEFT_TO_RIGHT": "NEGATIVE_X",  # -X (left) overwrites +X (right)
        "RIGHT_TO_LEFT": "POSITIVE_X",  # +X (right) overwrites -X (left)
    }
    blender_direction = direction_map.get(direction)
    if blender_direction is None:
        return error_response(
            f"Unknown direction '{direction}'. Valid: LEFT_TO_RIGHT, RIGHT_TO_LEFT."
        )

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)

        # Select all bones for symmetrize
        with temp_override("VIEW_3D"):
            bpy.ops.armature.select_all(action="SELECT")
            ok, res = safe_operator_call(
                bpy.ops.armature.symmetrize, direction=blender_direction
            )

        if not ok:
            return error_response(f"Symmetrize failed: {res}")

        return ok_response({
            "armature_name": armature_name,
            "direction": direction,
        })
    except Exception as e:
        return error_response(f"Failed to symmetrize armature: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_bone_layers(params):
    """
    Assign a bone to layers (3.x) or bone collections (4.x).
    Route: armature/bone-layers
    """
    armature_name = params.get("armature_name")
    bone_name = params.get("bone_name")
    layers = params.get("layers")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not bone_name:
        return error_response("Parameter 'bone_name' is required.")
    if layers is None:
        return error_response("Parameter 'layers' is required.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        if is_blender_4():
            # Blender 4.x: use bone collections
            # layers should be a list of collection name strings
            _enter_edit_mode(obj)

            edit_bone = obj.data.edit_bones.get(bone_name)
            if edit_bone is None:
                return error_response(
                    f"Bone '{bone_name}' not found in armature '{armature_name}'."
                )

            # Remove bone from all existing collections first
            for coll in list(edit_bone.collections):
                edit_bone.collections.unlink(coll)

            assigned = []
            for coll_name in layers:
                coll_name = str(coll_name)
                # Get or create the bone collection
                coll = obj.data.collections.get(coll_name)
                if coll is None:
                    coll = obj.data.collections.new(name=coll_name)
                coll.assign(edit_bone)
                assigned.append(coll_name)

            return ok_response({
                "armature_name": armature_name,
                "bone_name": bone_name,
                "collections": assigned,
            })

        else:
            # Blender 3.x: use bone.layers (32-element boolean tuple)
            _enter_edit_mode(obj)

            edit_bone = obj.data.edit_bones.get(bone_name)
            if edit_bone is None:
                return error_response(
                    f"Bone '{bone_name}' not found in armature '{armature_name}'."
                )

            layer_list = [False] * 32
            valid_indices = []
            for idx in layers:
                idx = int(idx)
                if 0 <= idx <= 31:
                    layer_list[idx] = True
                    valid_indices.append(idx)

            edit_bone.layers = tuple(layer_list)

            return ok_response({
                "armature_name": armature_name,
                "bone_name": bone_name,
                "layer_indices": valid_indices,
            })

    except Exception as e:
        return error_response(f"Failed to set bone layers: {e}")
    finally:
        _exit_to_object_mode()


def _handle_armature_rename_bones(params):
    """
    Batch rename bones in an armature.
    Route: armature/rename-bones
    """
    armature_name = params.get("armature_name")
    mapping = params.get("mapping")

    if not armature_name:
        return error_response("Parameter 'armature_name' is required.")
    if not mapping or not isinstance(mapping, dict):
        return error_response("Parameter 'mapping' must be a non-empty object.")

    obj, err = _get_armature_object(armature_name)
    if err:
        return err

    try:
        _enter_edit_mode(obj)

        results = {}
        renamed_count = 0

        for old_name, new_name in mapping.items():
            edit_bone = obj.data.edit_bones.get(old_name)
            if edit_bone is None:
                results[old_name] = f"NOT FOUND"
            else:
                edit_bone.name = str(new_name)
                actual_new = edit_bone.name  # Blender may adjust for uniqueness
                results[old_name] = actual_new
                renamed_count += 1

        return ok_response({
            "armature_name": armature_name,
            "renamed_count": renamed_count,
            "mapping_results": results,
        })
    except Exception as e:
        return error_response(f"Failed to rename bones: {e}")
    finally:
        _exit_to_object_mode()


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("armature", "create",                _handle_armature_create)
register_handler("armature", "add-bone",              _handle_armature_add_bone)
register_handler("armature", "edit-bone",             _handle_armature_edit_bone)
register_handler("armature", "delete-bone",           _handle_armature_delete_bone)
register_handler("armature", "parent-to-mesh",        _handle_armature_parent_to_mesh)
register_handler("armature", "list-bones",            _handle_armature_list_bones)
register_handler("armature", "set-bone-constraint",   _handle_armature_set_bone_constraint)
register_handler("armature", "remove-constraint",     _handle_armature_remove_constraint)
register_handler("armature", "set-ik",                _handle_armature_set_ik)
register_handler("armature", "auto-rig",              _handle_armature_auto_rig)
register_handler("armature", "weight-paint-auto",     _handle_armature_weight_paint_auto)
register_handler("armature", "weight-paint-normalize", _handle_armature_weight_paint_normalize)
register_handler("armature", "weight-assign",         _handle_armature_weight_assign)
register_handler("armature", "pose-bone",             _handle_armature_pose_bone)
register_handler("armature", "pose-reset",            _handle_armature_pose_reset)
register_handler("armature", "symmetrize",            _handle_armature_symmetrize)
register_handler("armature", "bone-layers",           _handle_armature_bone_layers)
register_handler("armature", "rename-bones",          _handle_armature_rename_bones)
