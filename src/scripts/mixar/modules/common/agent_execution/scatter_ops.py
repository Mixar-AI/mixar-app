# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, upright linked-object scatter in the current Blender process."""


def linked_scatter(source, placements, *, prefix, start_index=0, parent=None):
    """Place up to 128 separate named objects sharing one prepared source mesh.

    Each placement is {position: (world x,y,ground z), height: positive meters,
    yaw: radians (default 0), embed: meters below ground (default 0)}. Source
    object transforms are ignored; mesh local Z is upright. Bounds are read
    once per batch, never per instance. Use separate script steps for batches.
    The source must already have its modifiers baked and DATA material links.
    """
    import math
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    from .mesh_ops import mesh_bounds

    scene = bpy.context.scene
    if source.type != "MESH" or scene.objects.get(source.name) != source:
        raise ValueError("Scatter source must be a mesh in the current scene")
    if (source.modifiers or source.constraints or source.animation_data
            or any(slot.link != "DATA" for slot in source.material_slots)):
        raise ValueError("Prepare the source: bake modifiers; use DATA materials and no constraints/animation")
    if parent is not None and scene.objects.get(parent.name) != parent:
        raise ValueError("Scatter parent must belong to the current scene")
    rows = list(placements)
    if not rows or len(rows) > 128:
        raise ValueError("Use 1–128 placements per script step; split larger scatters into steps")
    if not isinstance(prefix, str) or not prefix or not isinstance(start_index, int) or start_index < 0:
        raise ValueError("Provide a name prefix and a nonnegative start_index")
    lo, hi = mesh_bounds(source.data)
    span = float(hi[2] - lo[2])
    if span <= 0:
        raise ValueError("Scatter source must have positive local Z height")
    prepared = []
    for i, row in enumerate(rows, start_index):
        position = tuple(float(v) for v in row["position"])
        height, yaw, embed = float(row["height"]), float(row.get("yaw", 0)), float(row.get("embed", 0))
        if (len(position) != 3 or height <= 0 or embed < 0
                or not all(math.isfinite(v) for v in (*position, height, yaw, embed))):
            raise ValueError("Scatter placements must be finite with positive height and nonnegative embed")
        name = f"{prefix}_{i:04d}"
        if bpy.data.objects.get(name) is not None:
            raise ValueError("Scatter object name already exists: " + name)
        factor = height / span
        origin = (*position[:2], position[2] - float(lo[2]) * factor - embed)
        matrix = Matrix.LocRotScale(Vector(origin), Quaternion((0, 0, 1), yaw), Vector((factor,) * 3))
        prepared.append((name, matrix))
    created = []
    try:
        for name, matrix in prepared:
            obj = source.copy()
            created.append(obj)
            obj.name = name
            obj.data = source.data
            obj.parent = parent
            obj.matrix_parent_inverse.identity()
            obj.matrix_world = matrix
            obj.hide_viewport = False
            obj.hide_render = False
            # The pristine cache identity belongs only to its parked source.
            if "ter_asset_id" in obj:
                del obj["ter_asset_id"]
            scene.collection.objects.link(obj)
        return created
    except Exception:
        for obj in created:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise
