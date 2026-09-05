# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Six-view capture job for an already-open scene; collection changes are a separate step.

The caller drives begin_view()/finish_view() around asynchronous render completion, inspects
the images, and calls isolate_and_save() only after every view has completed successfully.
This keeps the original file untouched and writes a full copy, retaining excluded geometry.
"""

import json
import math
from pathlib import Path

from .constants import SIX_VIEW_AXES, SIX_VIEW_COLLECTION
from .result import read_result


def _write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class SixViewJob:
    def __init__(self, output_directory, *, resolution=2048, samples=64):
        import bpy
        from mathutils import Vector

        self.scene = bpy.context.scene
        self.view_layer = bpy.context.view_layer
        self.output = Path(output_directory).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.source_path = bpy.data.filepath
        self.view_layer.update()
        self.source_meshes = [o for o in self.view_layer.objects
                              if o.type == "MESH" and not o.hide_render]
        if not self.source_meshes:
            raise RuntimeError("No render-enabled meshes in the current view layer")
        self.original_uids = {o.session_uid for o in self.source_meshes}
        lo, hi = Vector((math.inf,) * 3), Vector((-math.inf,) * 3)
        for obj in self.source_meshes:
            for corner in obj.bound_box:
                p = obj.matrix_world @ Vector(corner)
                for axis in range(3):
                    lo[axis], hi[axis] = min(lo[axis], p[axis]), max(hi[axis], p[axis])
        self.center = (lo + hi) / 2
        self.dimensions = hi - lo
        self.captures = {}
        self.active_view = None
        self.isolated = False
        self.manifest = dict(
            schema_version=1, source_file=self.source_path, scene=self.scene.name,
            original_scene_mesh_count=sum(o.type == "MESH" for o in self.scene.objects),
            source_render_mesh_count=len(self.source_meshes),
            bounds_min=list(lo), bounds_max=list(hi),
            resolution=resolution, samples=samples,
            transparency="preserve original materials; Dithered capture",
            identity_scope="session_uid applies only to this Blender session",
            collection_state=[dict(name=c.name, exclude=c.exclude,
                                   hide_viewport=c.hide_viewport)
                              for c in self.view_layer.layer_collection.children],
            views={}, status="prepared")

        self.setup = bpy.data.collections.new("Six View Render Setup")
        self.scene.collection.children.link(self.setup)
        self.cameras = {}
        distance = max(self.dimensions) * 2
        for name, axis in SIX_VIEW_AXES.items():
            data = bpy.data.cameras.new("Capture " + name.title())
            camera = bpy.data.objects.new(data.name, data)
            self.setup.objects.link(camera)
            camera.location = self.center + Vector(axis) * distance
            direction = self.center - camera.location
            camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
            data.type = "ORTHO"
            data.clip_start = max(distance / 10000, 0.0001)
            data.clip_end = distance * 4
            # Square images: project the bounding box into camera coordinates and add margin.
            inverse_rotation = camera.rotation_euler.to_matrix().transposed()
            projected = [inverse_rotation @ Vector((x, y, z))
                         for x in (-self.dimensions.x / 2, self.dimensions.x / 2)
                         for y in (-self.dimensions.y / 2, self.dimensions.y / 2)
                         for z in (-self.dimensions.z / 2, self.dimensions.z / 2)]
            width = max(p.x for p in projected) - min(p.x for p in projected)
            height = max(p.y for p in projected) - min(p.y for p in projected)
            data.ortho_scale = max(width, height) * 1.08
            self.cameras[name] = camera

        # Shadow-free inspection illumination: six opposite directions avoid a dark underside.
        for name, axis in SIX_VIEW_AXES.items():
            data = bpy.data.lights.new("Inspection " + name, "SUN")
            data.energy = 0.8
            data.use_shadow = False
            light = bpy.data.objects.new(data.name, data)
            self.setup.objects.link(light)
            light.rotation_euler = (-Vector(axis)).to_track_quat('-Z', 'Y').to_euler()
        world = bpy.data.worlds.new("Six View Inspection World")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.08, 0.08, 0.08, 1)
        self.scene.world = world
        self.scene.render.engine = "BLENDER_EEVEE"
        self.scene.render.resolution_x = self.scene.render.resolution_y = resolution
        self.scene.render.resolution_percentage = 100
        self.scene.render.image_settings.file_format = "PNG"
        self.scene.render.image_settings.color_mode = "RGBA"
        self.scene.render.film_transparent = False
        self.scene.render.use_compositing = False
        self.scene.render.use_sequencer = False
        self.scene.render.use_border = False
        self.scene.render.use_multiview = False
        self.scene.render.use_motion_blur = False
        self.scene.eevee.taa_render_samples = samples
        self.scene.eevee.use_raytracing = False
        for layer in self.scene.view_layers:
            layer.use = layer == self.view_layer
        self.scene.camera = self.cameras["front"]
        self.view_layer.update()
        _write_json(self.output / "manifest.json", self.manifest)

    def begin_view(self, name):
        import bpy

        if bpy.app.is_job_running("RENDER") or self.active_view:
            raise RuntimeError("Finish the current view before starting another")
        if self.isolated:
            raise RuntimeError("Cannot capture the full source after isolation")
        camera = self.cameras[name]
        self.scene.camera = camera
        self.scene.render.filepath = str(self.output / (name + ".png"))
        self.view_layer.update()
        self.active_view = name
        result = bpy.ops.render.render('INVOKE_DEFAULT', write_still=True,
                                      capture_visible_objects=True)
        if result != {'RUNNING_MODAL'}:
            self.active_view = None
            raise RuntimeError(f"Render did not start: {result}")
        return dict(view=name, camera=camera.name, filepath=self.scene.render.filepath)

    def finish_view(self):
        import bpy

        if bpy.app.is_job_running("RENDER"):
            raise RuntimeError("Render is still running")
        if self.active_view is None:
            raise RuntimeError("No pending view")
        result = read_result(self.scene)
        if not result["objects"]:
            raise RuntimeError("A car view unexpectedly captured no meshes")
        if not {o['session_uid'] for o in result['objects']} <= self.original_uids:
            raise RuntimeError("Capture contains meshes outside the source view layer")
        name = self.active_view
        result.update(view=name, camera=self.cameras[name].name,
                      camera_matrix=[list(row) for row in self.cameras[name].matrix_world])
        self.captures[name] = result
        _write_json(self.output / (name + ".objects.json"), result)
        self.manifest["views"][name] = dict(objects=len(result["objects"]),
                                            image=name + ".png",
                                            object_list=name + ".objects.json")
        self.active_view = None
        self.manifest["status"] = "captured" if len(self.captures) == 6 else "capturing"
        _write_json(self.output / "manifest.json", self.manifest)
        return dict(view=name, objects=len(result["objects"]))

    def isolate_and_save(self, filename="input-exterior.mixar"):
        import bpy

        if set(self.captures) != set(SIX_VIEW_AXES) or self.active_view or self.isolated:
            raise RuntimeError("Six completed views are required before isolation")
        destination = (self.output / filename).resolve()
        if destination == Path(self.source_path).resolve() or destination.exists():
            raise RuntimeError("Refusing to overwrite the input or an existing output")
        union = {entry['session_uid']: entry for capture in self.captures.values()
                 for entry in capture['objects']}
        by_uid = {o.session_uid: o for o in self.source_meshes}
        objects = [by_uid[uid] for uid in sorted(union)]
        transforms = {o: o.matrix_world.copy() for o in objects}
        ancestors = set()
        for obj in objects:
            parent = obj.parent
            while parent:
                if parent.type != 'EMPTY' and parent.session_uid not in union:
                    raise RuntimeError(f"Uncaptured non-empty parent needs explicit handling: {parent.name}")
                ancestors.add(parent)
                parent = parent.parent

        exterior = bpy.data.collections.new(SIX_VIEW_COLLECTION)
        self.scene.collection.children.link(exterior)
        hierarchy = bpy.data.collections.new("Assembly Transforms")
        exterior.children.link(hierarchy)
        for parent in ancestors:
            if parent.type == 'EMPTY':
                hierarchy.objects.link(parent)
        for obj in objects:
            memberships = list(obj.users_collection)
            exterior.objects.link(obj)
            for collection in memberships:
                collection.objects.unlink(obj)
        exterior.children.link(self.setup)
        self.scene.collection.children.unlink(self.setup)
        self.view_layer.update()
        for child in self.view_layer.layer_collection.children:
            child.exclude = child.collection != exterior
        self.view_layer.update()
        for obj, before in transforms.items():
            error = max(abs(before[r][c] - obj.matrix_world[r][c])
                        for r in range(4) for c in range(4))
            if error > 1e-5:
                raise RuntimeError(f"Object moved during isolation: {obj.name} ({error})")
        visible_meshes = {o.session_uid for o in self.view_layer.objects
                          if o.type == 'MESH' and not o.hide_render}
        if visible_meshes != set(union):
            raise RuntimeError("Enabled meshes do not match the six-view union")
        _write_json(self.output / "union.objects.json",
                    dict(objects=[union[uid] for uid in sorted(union)], count=len(union)))
        self.manifest.update(status="isolated", union_mesh_count=len(union),
                             excluded_active_mesh_count=len(self.source_meshes) - len(union),
                             output_file=str(destination), collection=exterior.name,
                             preserved_parent_empties=sum(p.type == 'EMPTY' for p in ancestors))
        _write_json(self.output / "manifest.json", self.manifest)
        self.scene.camera = self.cameras["front"]
        bpy.ops.wm.save_as_mainfile(filepath=str(destination), check_existing=False, compress=False)
        self.isolated = True
        self.manifest["status"] = "saved"
        _write_json(self.output / "manifest.json", self.manifest)
        return self.manifest
