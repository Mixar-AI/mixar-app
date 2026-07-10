# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared asset-preview rendering helpers.

Extracted from asset_inspect_ops so both the embedding-training flow
(512x512 previews for every library asset) and the chat asset-picker
(one-off 256x256 thumbnails for multi-match HITL) use the same rig:
EEVEE + transparent film + temp 3/4-view camera + key/fill lights,
with every other scene object hidden from the render.
"""

import os
import tempfile
from math import cos, radians, sin, tan

import bpy
from mathutils import Vector

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Mapping of object types to bpy.data collection names for cleanup
DATA_COLLECTIONS = {
    'MESH': 'meshes',
    'CURVE': 'curves',
    'SURFACE': 'curves',
    'META': 'metaballs',
    'FONT': 'curves',
    'CURVES': 'hair_curves',
    'POINTCLOUD': 'pointclouds',
    'VOLUME': 'volumes',
    'GPENCIL': 'grease_pencils',
    'GREASEPENCIL': 'grease_pencils',
    'ARMATURE': 'armatures',
    'LATTICE': 'lattices',
    'LIGHT': 'lights',
    'LIGHT_PROBE': 'lightprobes',
    'CAMERA': 'cameras',
    'SPEAKER': 'speakers',
}


def compute_bounds(objects):
    """Compute combined bounding box center and radius for objects."""
    all_corners = []
    for obj in objects:
        for corner in obj.bound_box:
            all_corners.append(obj.matrix_world @ Vector(corner))

    if not all_corners:
        return Vector((0, 0, 0)), 1.0

    min_co = Vector((
        min(c.x for c in all_corners),
        min(c.y for c in all_corners),
        min(c.z for c in all_corners),
    ))
    max_co = Vector((
        max(c.x for c in all_corners),
        max(c.y for c in all_corners),
        max(c.z for c in all_corners),
    ))

    center = (min_co + max_co) / 2
    radius = (max_co - min_co).length / 2
    return center, max(radius, 0.001)


def frame_camera(camera_obj, objects):
    """Position camera for a preview-style 3/4 view framing the objects."""
    center, radius = compute_bounds(objects)

    fov = camera_obj.data.angle
    distance = (radius / tan(fov / 2)) * 1.2

    elev = radians(25)
    azim = radians(45)
    offset = Vector((
        cos(elev) * sin(azim),
        -cos(elev) * cos(azim),
        sin(elev),
    )) * distance

    camera_obj.location = center + offset
    direction = center - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def render_to_image(scene, image_name, pack=True):
    """Render the scene, save to temp JPEG, load back as a bpy image.

    Args:
        scene: The scene to render (rig already set up).
        image_name: Name for the resulting bpy.data.images entry.
        pack: Pack the image into the .blend (True for training previews
            that must survive; False for transient UI thumbnails).
    """
    temp_path = os.path.join(tempfile.gettempdir(), f"{image_name}.jpg")

    # Temporarily switch output format to JPEG with 80% quality
    orig_format = scene.render.image_settings.file_format
    orig_quality = scene.render.image_settings.quality
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 80

    try:
        bpy.ops.render.render()

        render_img = bpy.data.images.get('Render Result')
        if not render_img:
            return None

        render_img.save_render(filepath=temp_path, scene=scene)

        existing = bpy.data.images.get(image_name)
        if existing:
            bpy.data.images.remove(existing)

        img = bpy.data.images.load(temp_path)
        img.name = image_name
        if pack:
            img.pack()
        return img
    finally:
        scene.render.image_settings.file_format = orig_format
        scene.render.image_settings.quality = orig_quality
        if os.path.exists(temp_path):
            os.remove(temp_path)


def remove_objects(objects):
    """Delete objects and their orphan data-blocks."""
    for obj in objects:
        data = obj.data
        obj_type = obj.type
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0:
            coll_attr = DATA_COLLECTIONS.get(obj_type)
            if coll_attr and hasattr(bpy.data, coll_attr):
                getattr(bpy.data, coll_attr).remove(data)


def remove_collection(collection):
    """Delete a collection and all its objects and orphan data."""
    objects = list(collection.all_objects)
    remove_objects(objects)
    bpy.data.collections.remove(collection)


class PreviewRenderRig:
    """Context manager that turns the current scene into an asset-preview
    stage and restores it on exit.

    Setup: EEVEE, size x size, transparent film, temp camera (set as the
    scene camera) + key/fill sun lights, and every pre-existing object
    hidden from the render. Exposes `.camera` for frame_camera().
    """

    def __init__(self, scene, size=512):
        self.scene = scene
        self.size = size
        self.camera = None
        self._orig = None
        self._temp = []          # (object, data_collection, data) tuples
        self._hidden = []

    def __enter__(self):
        scene = self.scene
        self._orig = {
            'engine': scene.render.engine,
            'res_x': scene.render.resolution_x,
            'res_y': scene.render.resolution_y,
            'res_pct': scene.render.resolution_percentage,
            'camera': scene.camera,
            'film_transparent': scene.render.film_transparent,
        }

        try:
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
        except Exception:
            scene.render.engine = 'BLENDER_EEVEE'
        scene.render.resolution_x = self.size
        scene.render.resolution_y = self.size
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True

        cam_data = bpy.data.cameras.new("_asset_preview_cam")
        cam_obj = bpy.data.objects.new("_asset_preview_cam", cam_data)
        scene.collection.objects.link(cam_obj)
        scene.camera = cam_obj
        self.camera = cam_obj
        self._temp.append((cam_obj, bpy.data.cameras, cam_data))

        key_data = bpy.data.lights.new("_asset_preview_key", 'SUN')
        key_data.energy = 3.0
        key_obj = bpy.data.objects.new("_asset_preview_key", key_data)
        key_obj.rotation_euler = (radians(50), 0, radians(30))
        scene.collection.objects.link(key_obj)
        self._temp.append((key_obj, bpy.data.lights, key_data))

        fill_data = bpy.data.lights.new("_asset_preview_fill", 'SUN')
        fill_data.energy = 1.0
        fill_obj = bpy.data.objects.new("_asset_preview_fill", fill_data)
        fill_obj.rotation_euler = (radians(30), 0, radians(-150))
        scene.collection.objects.link(fill_obj)
        self._temp.append((fill_obj, bpy.data.lights, fill_data))

        temp_objs = {t[0] for t in self._temp}
        for obj in list(scene.objects):
            if obj not in temp_objs and not obj.hide_render:
                obj.hide_render = True
                self._hidden.append(obj)

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        scene = self.scene
        for obj in self._hidden:
            if obj.name in bpy.data.objects:
                obj.hide_render = False

        for obj, data_coll, data in self._temp:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                data_coll.remove(data)
            except Exception:
                pass

        orig = self._orig or {}
        scene.render.engine = orig.get('engine', scene.render.engine)
        scene.render.resolution_x = orig.get('res_x', scene.render.resolution_x)
        scene.render.resolution_y = orig.get('res_y', scene.render.resolution_y)
        scene.render.resolution_percentage = orig.get(
            'res_pct', scene.render.resolution_percentage)
        scene.render.film_transparent = orig.get(
            'film_transparent', scene.render.film_transparent)
        scene.camera = orig.get('camera')
        return False
