# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material preview renders for embedding: a flat SWATCH and a studio SPHERE.

A material is embedded from two images, one vector each (the backend keeps a
material's best-scoring view):

* ``swatch`` — an orthographic, front-on 2 m tile. A reference PHOTO of a
  surface (a brick wall, scratched steel) looks like this, so image queries
  match it.
* ``sphere`` — a lit sphere against a neutral grey studio. Gloss, metalness,
  glass and subsurface read here, so text such as "polished gold" matches it.

Both views are always rendered (never the asset's embedded thumbnail): the
two must look the same for every material in every library, or vectors drift
with whoever made the thumbnail.

DELIBERATELY self-contained (bpy + bmesh + stdlib only): the headless preview
worker imports it from this directory under ``--factory-startup``, where no
``mixar`` package exists. The caller owns the render rig (EEVEE, camera, the
two suns) and passes ``render_fn(scene, out_path) -> bool``.
"""

from math import radians, tan

import bmesh
import bpy
from mathutils import Vector

VIEWS = ("swatch", "sphere")
# The view written back as the asset's thumbnail when its .blend has none:
# a lit sphere is what Blender's own material previews show.
THUMBNAIL_VIEW = "sphere"
_STUDIO_GREY = (0.18, 0.18, 0.18)
_SWATCH_SIZE = 2.0          # metres; the plane's UVs span 0..1 across it
_SPHERE_RADIUS = 1.0


class AppendedData:
    """Remove every material, image, node group, texture and mesh created
    inside the block, once nothing but its own fake user holds it.

    The in-app render runs in the user's file: nothing the preview needed may
    outlive it. A material marked as an asset carries a fake user, so an
    appended object's material would otherwise survive its object and be
    saved into the user's file.
    """

    # Order matters: materials first so their images and groups drop to zero.
    _TRACKED = ("materials", "node_groups", "textures", "images", "meshes")

    def __init__(self):
        self._before = {}

    def __enter__(self):
        self._before = {attr: set(getattr(bpy.data, attr)) for attr in self._TRACKED}
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for attr in self._TRACKED:
            collection = getattr(bpy.data, attr)
            for block in [b for b in collection if b not in self._before[attr]]:
                if block.users - int(block.use_fake_user) > 0:
                    continue
                try:
                    collection.remove(block)
                except Exception:
                    pass
        return False


class AppendedMaterial(AppendedData):
    """LINK one material from a .blend for a preview; on exit remove the
    library datablock the link created, which takes the material and its
    images and node groups with it.

    Never appended: Blender moves a library ID's weak reference to the newest
    appended copy, so a preview append would strip it from a copy the user
    applied earlier, and the next Apply could no longer reuse it (`.001`).
    A library the user already links is left in place.
    """

    def __init__(self, blend_path, name):
        super().__init__()
        self.blend_path = blend_path
        self.name = name
        self.material = None
        self._libraries_before = set()

    def __enter__(self):
        super().__enter__()
        self._libraries_before = set(bpy.data.libraries)
        with bpy.data.libraries.load(self.blend_path, link=True) as (data_from, data_to):
            if self.name in data_from.materials:
                data_to.materials = [self.name]
        if data_to.materials:
            self.material = data_to.materials[0]
        return self.material

    def __exit__(self, exc_type, exc_value, traceback):
        for library in [lib for lib in bpy.data.libraries if lib not in self._libraries_before]:
            try:
                bpy.data.libraries.remove(library)
            except Exception:
                pass
        return super().__exit__(exc_type, exc_value, traceback)


def has_embedded_preview(datablock, min_size=32):
    """True when ``datablock`` carries a usable embedded preview: big enough
    and not fully transparent (the same test the reuse path applies)."""
    preview = getattr(datablock, "preview", None)
    if preview is None:
        return False
    w, h = preview.image_size
    if w < min_size or h < min_size:
        return False
    try:
        import numpy as np
        buf = np.empty(w * h * 4, dtype=np.float32)
        preview.image_pixels_float.foreach_get(buf)
    except Exception:
        return False
    return float(buf[3::4].max(initial=0.0)) >= 0.05


def thumbnail_entry(item, paths, views, has_preview):
    """The thumbnail backfill entry for a rendered material, or None when its
    .blend already has a preview (never overwritten) or the view failed."""
    if has_preview or THUMBNAIL_VIEW not in views:
        return None
    return {"blend_str": item["blend_str"], "name": item["name"],
            "jpg": paths[THUMBNAIL_VIEW], "kind": "MATERIAL"}


def _mesh_object(name, build, material):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        build(bm)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.materials.append(material)
    return bpy.data.objects.new(name, mesh)


def _build_swatch(bm):
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=_SWATCH_SIZE / 2, calc_uvs=True)


def _build_sphere(bm):
    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=_SPHERE_RADIUS, calc_uvs=True)
    for face in bm.faces:
        face.smooth = True


def _studio_world():
    world = bpy.data.worlds.new("_mixar_material_preview_world")
    world.color = _STUDIO_GREY
    try:
        world.use_nodes = True
    except Exception:
        pass
    tree = getattr(world, "node_tree", None)
    for node in getattr(tree, "nodes", ()) or ():
        if node.type == "BACKGROUND":
            node.inputs["Color"].default_value = (*_STUDIO_GREY, 1.0)
            node.inputs["Strength"].default_value = 1.0
    return world


def _remove_object(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _aim_sphere_camera(camera):
    fov = camera.data.angle
    distance = (_SPHERE_RADIUS / tan(fov / 2)) * 1.25
    direction = Vector((0.5, -0.8, 0.35)).normalized()
    camera.location = direction * distance
    camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()


def render_views(scene, camera, material, out_paths, render_fn):
    """Render ``material`` for every view in ``out_paths`` ({view: jpg path}).

    Returns the views that produced an image. Every temporary object, the
    studio world and the camera/film settings are restored before returning.
    """
    cam_data = camera.data
    saved = {
        "world": scene.world,
        "film": scene.render.film_transparent,
        "cam_type": cam_data.type,
        "ortho": cam_data.ortho_scale,
        "location": camera.location.copy(),
        "rotation": camera.rotation_euler.copy(),
    }
    world = _studio_world()
    scene.world = world
    # Opaque studio background: glass and alpha materials over a transparent
    # film would render as nothing.
    scene.render.film_transparent = False
    rendered = []
    try:
        for view in VIEWS:
            path = out_paths.get(view)
            if not path:
                continue
            build = _build_swatch if view == "swatch" else _build_sphere
            obj = _mesh_object(f"_mixar_material_preview_{view}", build, material)
            scene.collection.objects.link(obj)
            try:
                if view == "swatch":
                    cam_data.type = "ORTHO"
                    cam_data.ortho_scale = _SWATCH_SIZE
                    camera.location = (0.0, 0.0, 4.0)
                    camera.rotation_euler = (0.0, 0.0, radians(0.0))
                else:
                    cam_data.type = "PERSP"
                    _aim_sphere_camera(camera)
                bpy.context.view_layer.update()
                if render_fn(scene, path):
                    rendered.append(view)
            finally:
                _remove_object(obj)
    finally:
        scene.world = saved["world"]
        scene.render.film_transparent = saved["film"]
        cam_data.type = saved["cam_type"]
        cam_data.ortho_scale = saved["ortho"]
        camera.location = saved["location"]
        camera.rotation_euler = saved["rotation"]
        try:
            bpy.data.worlds.remove(world)
        except Exception:
            pass
    return rendered
