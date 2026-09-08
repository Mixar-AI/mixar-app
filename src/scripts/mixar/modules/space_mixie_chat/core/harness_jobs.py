# SPDX-License-Identifier: GPL-3.0-or-later
"""Path-free Jasper submission for the backend harness."""

import os
import tempfile

import bpy


def segment_mesh(object_name, description, expected_parts, model):
    from mixar.modules.mesh_segment.core.mesh_segment_queue import (
        enqueue_mesh_segment_job,
    )

    obj = bpy.context.scene.objects.get(object_name)
    if obj is None or obj.type != "MESH":
        return {"success": False, "error": "Target mesh is not in this scene"}
    if not obj.data.uv_layers:
        return {
            "success": False,
            "error": "Unwrap the target mesh before UV segmentation",
        }
    selected = [o.name for o in bpy.context.selected_objects]
    active = getattr(bpy.context.view_layer.objects.active, "name", None)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        with tempfile.TemporaryDirectory(prefix="mixar-segment-") as directory:
            path = os.path.join(directory, "mesh.obj")
            status = bpy.ops.wm.obj_export(
                filepath=path,
                export_selected_objects=True,
                export_uv=True,
                export_normals=True,
                export_materials=False,
            )
            if "FINISHED" not in status:
                return {
                    "success": False,
                    "error": "Could not prepare mesh for segmentation",
                }
            job = enqueue_mesh_segment_job(
                mesh_object_name=obj.name,
                mesh_file_path=path,
                description=description,
                expected_parts=expected_parts,
                model=model,
            )
        if job is None:
            return {"success": False, "error": "Segmentation could not be queued"}
        return {"success": True, "job_ids": [job.id]}
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for name in selected:
            item = bpy.context.scene.objects.get(name)
            if item:
                item.select_set(True)
        if active and bpy.context.scene.objects.get(active):
            bpy.context.view_layer.objects.active = bpy.context.scene.objects[active]
