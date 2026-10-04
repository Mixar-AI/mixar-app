# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bulk geometry operations for scripts running in the current Blender process.

Objects must belong to the routed scene. Nothing here starts a worker, runs bpy
on a thread, or pumps nested UI events. Call bounded operations in separate
script steps to return control to Blender between batches.
"""


def read_positions(mesh):
    """Return an independent contiguous float32 (vertex_count, 3) array."""
    import numpy as np

    positions = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", positions.ravel())
    return positions


def mesh_bounds(mesh):
    """Fresh local-space bounds of the base mesh, using one bulk RNA read.

    Call once per source mesh before a placement/verification loop, then reuse
    the returned arrays. There is deliberately no cache across mesh edits.
    """
    import numpy as np

    if mesh.is_editmode:
        raise ValueError("Base mesh bounds require Object mode")
    xyz = read_positions(mesh)
    if not len(xyz) or not np.isfinite(xyz).all():
        raise ValueError("Mesh bounds require nonempty, finite coordinates")
    return xyz.min(axis=0), xyz.max(axis=0)


def write_positions(mesh, positions):
    """Write all base coordinates once; refuse shape-key or Edit-mode meshes.

    The caller decides whether to copy a shared mesh before editing. Topology,
    UVs, materials, custom attributes and object transforms are preserved.
    """
    import numpy as np

    if mesh.is_editmode or mesh.shape_keys is not None:
        raise ValueError("Bulk base-coordinate edits require Object mode and no shape keys")
    values = np.asarray(positions, dtype=np.float32)
    if values.shape != (len(mesh.vertices), 3) or not np.isfinite(values).all():
        raise ValueError("positions must be finite with shape (vertex_count, 3)")
    mesh.vertices.foreach_set("co", np.ascontiguousarray(values).ravel())
    mesh.update()


def fill_material_index(mesh, index=0):
    """Set a uniform polygon material index without a Python/RNA face loop."""
    import numpy as np

    if mesh.is_editmode:
        raise ValueError("Material index filling requires Object mode")
    if not isinstance(index, int) or not 0 <= index < max(1, len(mesh.materials)):
        raise ValueError("Material index is outside the mesh's material slots")
    mesh.polygons.foreach_set("material_index", np.full(len(mesh.polygons), index, dtype=np.int32))
    mesh.update()


def _combined_cutter(cutters):
    """One operand, retaining disjoint shells and accounting for mirrored scales."""
    import bpy
    import numpy as np

    from .boolean_prepare import bounds_overlap
    positions, faces, axes = [], [], []
    offset = 0
    for obj in cutters:
        mesh = obj.data
        xyz = read_positions(mesh)
        matrix = np.asarray(obj.matrix_world, dtype=np.float64)
        xyz = xyz @ matrix[:3, :3].T + matrix[:3, 3]
        if not np.isfinite(xyz).all():
            raise ValueError("Boolean cutters must have finite world coordinates")
        positions.append(xyz)
        axes.append(matrix[:3, :3].T)
        indices = np.empty(len(mesh.loops), dtype=np.int32)
        starts = np.empty(len(mesh.polygons), dtype=np.int32)
        counts = np.empty(len(mesh.polygons), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", indices)
        mesh.polygons.foreach_get("loop_start", starts)
        mesh.polygons.foreach_get("loop_total", counts)
        indices += offset
        reverse = np.linalg.det(matrix[:3, :3]) < 0
        for start, count in zip(starts, counts):
            face = indices[start:start + count].tolist()
            faces.append(face[::-1] if reverse else face)
        offset += len(xyz)
    overlap = bounds_overlap(positions, axes)
    mesh = bpy.data.meshes.new("_MixarBooleanOperand")
    obj = None
    try:
        mesh.from_pydata(np.concatenate(positions), [], faces)
        if mesh.validate(clean_customdata=False):
            raise ValueError("Invalid cutter topology; repair the source cutters explicitly")
        obj = bpy.data.objects.new("_MixarBooleanOperand", mesh)
        bpy.context.scene.collection.objects.link(obj)
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        raise
    return obj, overlap


def _closed_solid(mesh):
    """Conservative topology eligibility for Blender's native Manifold solver."""
    import bpy
    import bmesh

    probe = mesh.copy()
    bm = bmesh.new()
    try:
        if probe.validate(clean_customdata=False):
            raise ValueError("Invalid Boolean topology; repair the source mesh explicitly")
        bm.from_mesh(probe)
        return (bool(bm.faces) and all(e.is_manifold and e.is_contiguous for e in bm.edges)
                and all(f.calc_area() > 0 for f in bm.faces) and bm.calc_volume(signed=True) > 0)
    finally:
        bm.free()
        bpy.data.meshes.remove(probe)


def boolean_difference(target, cutters, *, solver="AUTO"):
    """Apply all cutter volumes in ONE Boolean before finishing modifiers.

    Simple cutters have no modifiers; cutter face materials are not transferred
    (new cut faces use target material zero). Cutters remain unchanged and linked;
    the caller removes its temporary cutters after success. Only BEVEL and
    WEIGHTED_NORMAL finishing modifiers may already exist on the target. Their
    order and settings are preserved. Other stacks, shared target meshes and
    shape keys require an explicit preparation step by the caller.
    AUTO uses native MANIFOLD for closed, consistently oriented solids with
    provably disjoint cutters, otherwise EXACT. A single closed target shell
    with inconsistent winding is oriented on a private copy first. Multiple
    shells (potential cavities), open meshes and ambiguous cutters keep EXACT.
    EXACT can be requested explicitly and never reorients the target.
    The Boolean runs synchronously: split targets into separate script steps.
    """
    import bpy

    cutters = list(cutters)
    if solver not in {"AUTO", "EXACT"}:
        raise ValueError("solver must be AUTO or EXACT")
    scene = bpy.context.scene
    if bpy.context.mode != "OBJECT":
        raise ValueError("Batched Boolean cuts require Object mode")
    for obj in [target, *cutters]:
        if obj.type != "MESH" or scene.objects.get(obj.name) != obj:
            raise ValueError("Boolean target and cutters must be meshes in the current scene")
        if obj.data.is_editmode:
            raise ValueError("Boolean meshes must not be in Edit mode")
    if not cutters or target in cutters or len({o.as_pointer() for o in cutters}) != len(cutters):
        raise ValueError("Provide distinct cutters, excluding the target")
    if target.library or target.data.library or target.data.users != 1 or target.data.shape_keys:
        raise ValueError("Boolean target must be a local single-user mesh without shape keys")
    if any(m.type not in {"BEVEL", "WEIGHTED_NORMAL"} for m in target.modifiers):
        raise ValueError("Apply geometry modifiers explicitly before batching cuts; add finish modifiers last")
    if any(o.modifiers or not o.data.polygons for o in cutters):
        raise ValueError("Batch cutters must be nonempty meshes without modifiers; prepare them first")

    # A collection Boolean's n-ary exact solver was slower than sequential
    # cuts on the watch fixture. One disconnected operand keeps this a binary
    # solve without joining or changing any source cutter.
    operand = None
    modifier_name = None
    original_mesh = target.data
    repaired_mesh = None
    committed = False
    finishing = [(m, m.show_viewport) for m in target.modifiers]
    try:
        for item, _visible in finishing:
            item.show_viewport = False
        bpy.context.view_layer.update()
        operand, overlap = _combined_cutter(cutters)
        # Validate even explicit/fallback Exact inputs before entering native
        # Boolean code. Solver eligibility must not bypass topology safety.
        target_closed = _closed_solid(target.data)
        operand_closed = _closed_solid(operand.data)
        chosen = "EXACT"
        available = bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items
        if solver == "AUTO" and "MANIFOLD" in available and not overlap and operand_closed and not target_closed:
            from .boolean_prepare import oriented_copy
            repaired_mesh = oriented_copy(target.data)
            if repaired_mesh is not None:
                target.data = repaired_mesh
                target_closed = True
        if (solver == "AUTO" and "MANIFOLD" in available and not overlap
                and target_closed and operand_closed):
            chosen = "MANIFOLD"
        modifier = target.modifiers.new("Mixar_Batched_Cut", "BOOLEAN")
        modifier_name = modifier.name
        modifier.operation = "DIFFERENCE"
        modifier.material_mode = "INDEX"
        modifier.solver = chosen
        modifier.object = operand
        modifier.use_self = overlap
        target.modifiers.move(len(target.modifiers) - 1, 0)
        with bpy.context.temp_override(object=target, active_object=target,
                                       selected_objects=[target], selected_editable_objects=[target]):
            status = bpy.ops.object.modifier_apply(modifier=modifier.name)
        if "FINISHED" not in status:
            raise RuntimeError("Batched Boolean application was cancelled")
        modifier_name = None
        committed = True
    finally:
        remaining = target.modifiers.get(modifier_name) if modifier_name else None
        if remaining is not None:
            target.modifiers.remove(remaining)
        for item, visible in finishing:
            item.show_viewport = visible
        if operand is not None:
            mesh = operand.data
            bpy.data.objects.remove(operand, do_unlink=True)
            bpy.data.meshes.remove(mesh)
        if repaired_mesh is not None:
            if not committed:
                failed_mesh = target.data
                target.data = original_mesh
                if failed_mesh.users == 0:
                    bpy.data.meshes.remove(failed_mesh)
            elif original_mesh.users == 0:
                bpy.data.meshes.remove(original_mesh)
    return {"cutters": len(cutters), "faces": len(target.data.polygons), "solver": chosen,
            "winding_repaired": repaired_mesh is not None}
