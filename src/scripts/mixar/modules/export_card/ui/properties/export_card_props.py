# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export card's settings: one group on WindowManager
(``wm.mixar_export_card``) — they last the session, so a second export lands
where the first did with the same choices, and nothing is written into the
user's file (WindowManager properties are never loaded back from a .blend).

3D settings mirror the exporter's effective values: picking an engine loads
its preset into them (`core/spec.sync_preset`)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ... import constants as C
from ...core import targets

_camera_items_cache = []


def _camera_items(_self, context):
    """The scene's cameras, the active one first (Blender keeps no reference
    to dynamic items: the module list holds them)."""
    scene = getattr(context, "scene", None)
    items = []
    if scene is not None:
        active = scene.camera
        cameras = sorted((obj for obj in scene.objects if obj.type == 'CAMERA'),
                         key=lambda obj: (obj != active, obj.name.lower()))
        items = [(obj.name, obj.name, "") for obj in cameras]
    if not items:
        items = [('NONE', "No camera in this scene", "")]
    _camera_items_cache[:] = items
    return _camera_items_cache


_TARGET_ITEMS = [(t.id, t.tile, "") for t in targets.TARGETS]
_ENGINE_ITEMS = [(e, e, "") for e in C.ENGINES]


class MixarExportCardProps(bpy.types.PropertyGroup):
    target: EnumProperty(name="Export", items=_TARGET_ITEMS, default=C.GLTF)  # type: ignore[valid-type]
    state: EnumProperty(name="State", items=[  # type: ignore[valid-type]
        (C.IDLE, "Idle", ""), (C.RUNNING, "Running", ""), ('CONFIRM', "Confirm", ""),
        (C.DONE, "Done", ""), (C.ERROR, "Error", "")], default=C.IDLE)
    show_advanced: BoolProperty(name="Advanced Settings", default=False)  # type: ignore[valid-type]

    # Destination.
    file_name: StringProperty(name="File Name", default="", maxlen=200)  # type: ignore[valid-type]
    folder: StringProperty(name="Folder", default="", subtype='DIR_PATH', maxlen=1024)  # type: ignore[valid-type]

    # 3D model.
    engine: EnumProperty(name="Made For", items=_ENGINE_ITEMS, default='web')  # type: ignore[valid-type]
    scope: EnumProperty(name="What to Export", items=[  # type: ignore[valid-type]
        ('SCENE', "Whole scene", ""), ('SELECTED', "Selected", "")], default='SCENE')
    animation: EnumProperty(name="Animation", items=[  # type: ignore[valid-type]
        ('ALL', "All clips", ""), ('NONE', "None", "")], default='ALL')
    gltf_file: EnumProperty(name="File", items=[  # type: ignore[valid-type]
        ('GLB', "GLB · one file", ""), ('GLTF', "glTF · separate files", "")], default='GLB')
    usd_file: EnumProperty(name="File", items=[  # type: ignore[valid-type]
        ('USDZ', "USDZ · packaged", ""), ('USDC', "USDC · binary", "")],
        default='USDZ')
    cameras_lights: BoolProperty(name="Cameras and Lights", default=False)  # type: ignore[valid-type]
    texture_format: EnumProperty(name="Textures", items=[  # type: ignore[valid-type]
        ('AUTO', "Auto", ""), ('JPEG', "JPEG", ""), ('WEBP', "WebP", ""),
        ('NONE', "None", "")], default='AUTO')
    draco: BoolProperty(name="Draco Compression", default=False)  # type: ignore[valid-type]
    apply_modifiers: BoolProperty(name="Apply Modifiers", default=True)  # type: ignore[valid-type]
    y_up: BoolProperty(name="Y Up", default=True)  # type: ignore[valid-type]
    fbx_embed: BoolProperty(name="Embed Textures", default=True)  # type: ignore[valid-type]
    fbx_scale: EnumProperty(name="Scale", items=[  # type: ignore[valid-type]
        ('FBX_SCALE_NONE', "Engine default", ""), ('FBX_SCALE_UNITS', "Apply units", ""),
        ('FBX_SCALE_ALL', "Apply all", "")], default='FBX_SCALE_NONE')
    leaf_bones: BoolProperty(name="Leaf Bones", default=False)  # type: ignore[valid-type]
    smoothing: EnumProperty(name="Smoothing", items=[  # type: ignore[valid-type]
        ('FACE', "Face", ""), ('EDGE', "Edge", ""), ('OFF', "Normals only", "")], default='FACE')
    obj_copy_textures: BoolProperty(name="Copy Textures", default=True)  # type: ignore[valid-type]
    stl_units: EnumProperty(name="Units", items=[  # type: ignore[valid-type]
        ('MM', "Millimetres", ""), ('CM', "Centimetres", ""), ('M', "Metres", "")], default='MM')
    stl_scale: FloatProperty(name="Scale", default=1.0, min=0.001, max=1000.0)  # type: ignore[valid-type]
    stl_ascii: BoolProperty(name="ASCII", default=False)  # type: ignore[valid-type]

    # Project copy.
    project_strip_chat: BoolProperty(name="Remove Agent Chat", default=False)  # type: ignore[valid-type]
    project_compress: BoolProperty(name="Compress", default=True)  # type: ignore[valid-type]

    # Image / Video.
    camera: EnumProperty(name="Camera", items=_camera_items)  # type: ignore[valid-type]
    render_format: EnumProperty(name="Format", items=[  # type: ignore[valid-type]
        ('PNG', "PNG", ""), ('JPEG', "JPG", ""), ('OPEN_EXR', "EXR", "")], default='PNG')
    transparent: BoolProperty(name="Transparent Background", default=False)  # type: ignore[valid-type]
    quality: EnumProperty(name="Quality", items=[  # type: ignore[valid-type]
        ('DRAFT', "Draft", ""), ('GOOD', "Good", ""), ('FINAL', "Final", "")], default='GOOD')
    renderer: EnumProperty(name="Renderer", items=[  # type: ignore[valid-type]
        ('EEVEE', "EEVEE", ""), ('CYCLES', "Cycles", "")], default='EEVEE')
    width: IntProperty(name="Width", default=1920, min=16, max=16384)  # type: ignore[valid-type]
    height: IntProperty(name="Height", default=1080, min=16, max=16384)  # type: ignore[valid-type]
    frame_start: IntProperty(name="Start", default=1, min=0, max=1048574)  # type: ignore[valid-type]
    frame_end: IntProperty(name="End", default=250, min=0, max=1048574)  # type: ignore[valid-type]
    fps: IntProperty(name="Frame Rate", default=24, min=1, max=240)  # type: ignore[valid-type]


classes = (MixarExportCardProps,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.mixar_export_card = bpy.props.PointerProperty(type=MixarExportCardProps)


def unregister():
    if hasattr(bpy.types.WindowManager, "mixar_export_card"):
        del bpy.types.WindowManager.mixar_export_card
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
