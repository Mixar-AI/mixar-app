# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D — Property Groups

Defines all Blender PropertyGroups for the Hunyuan module:
- MixieHunyuanMultiViewEntry: Single multi-view image slot (Pro mode)
- MixieHunyuanJobState: Per-mode job state (progress, status, etc.)
- MixieHunyuanProProps / RapidProps / PartProps / TopologyProps / UVProps
- MixieHunyuanProps: Root property group attached to Scene
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from ..constants import DEFAULT_FACE_COUNT


# ============================================================================
# MULTI-VIEW IMAGE ENTRY (Pro mode)
# ============================================================================


class MixieHunyuanMultiViewEntry(PropertyGroup):
    """A single multi-view image slot with view type and image reference."""

    view_type: EnumProperty(
        name="View Type",
        items=[
            ('left', "Left", ""),
            ('right', "Right", ""),
            ('back', "Back", ""),
            ('top', "Top", "Model 3.1 only"),
            ('bottom', "Bottom", "Model 3.1 only"),
            ('left_front', "Left Front", "Model 3.1 only"),
            ('right_front', "Right Front", "Model 3.1 only"),
        ],
        default='left',
    )
    image: PointerProperty(type=bpy.types.Image, name="Image")


# ============================================================================
# JOB STATE (independent per mode)
# ============================================================================


class MixieHunyuanJobState(PropertyGroup):
    """
    Tracks the lifecycle of a single Hunyuan generation job.

    Each mode (Pro, Rapid, Part, Topology, UV) has its own JobState,
    enabling concurrent jobs across different modes.
    """

    job_id: StringProperty(default="", options={'SKIP_SAVE'})
    api_type: StringProperty(default="", options={'SKIP_SAVE'})
    status: EnumProperty(
        items=[
            ('IDLE', "Idle", ""),
            ('SUBMITTING', "Submitting", ""),
            ('POLLING', "Polling", ""),
            ('DOWNLOADING', "Downloading", ""),
            ('DONE', "Done", ""),
            ('FAILED', "Failed", ""),
        ],
        default='IDLE',
        options={'SKIP_SAVE'},
    )
    progress: FloatProperty(min=0.0, max=1.0, default=0.0, subtype='FACTOR',
                            options={'SKIP_SAVE'})
    progress_label: StringProperty(default="", options={'SKIP_SAVE'})
    error_message: StringProperty(default="", options={'SKIP_SAVE'})
    result_files_json: StringProperty(default="", options={'SKIP_SAVE'})
    imported_object_name: StringProperty(default="", options={'SKIP_SAVE'})
    poll_count: IntProperty(default=0, options={'SKIP_SAVE'})
    poll_start_time: FloatProperty(default=0.0, options={'SKIP_SAVE'})


# ============================================================================
# PER-MODE INPUT PROPERTIES (each includes its own job state)
# ============================================================================


class MixieHunyuanUploadedImage(PropertyGroup):
    """A single uploaded image for Pro mode batch processing."""

    image: PointerProperty(type=bpy.types.Image, name="Image")


class MixieHunyuanProProps(PropertyGroup):
    """Input properties for Hunyuan 3D Pro mode."""

    prompt: StringProperty(name="Prompt", maxlen=1024, default="")
    image: PointerProperty(type=bpy.types.Image, name="Image")
    uploaded_images: CollectionProperty(type=MixieHunyuanUploadedImage)
    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image as main image. "
                    "OFF: Use uploaded image",
        default=True,
    )
    multi_views: CollectionProperty(type=MixieHunyuanMultiViewEntry)
    enable_pbr: BoolProperty(name="Enable PBR", default=False)
    face_count: IntProperty(
        name="Face Count",
        default=DEFAULT_FACE_COUNT,
        min=40000,
        max=1500000,
    )
    generate_type: EnumProperty(
        name="Generate Type",
        items=[
            ('Normal', "Normal", "Standard generation"),
            ('LowPoly', "LowPoly", "Low polygon output"),
            ('Geometry', "Geometry", "Geometry-only white model"),
            # 'Sketch' option hidden from the UI dropdown.
            # The backend (hunyuan_service.py) still accepts "Sketch" as a
            # generate_type when called directly from server-side flows.
        ],
        default='Normal',
    )
    polygon_type: EnumProperty(
        name="Polygon Type",
        items=[
            ('triangle', "Triangle", ""),
            ('quadrilateral', "Quadrilateral", ""),
        ],
        default='triangle',
    )
    model_version: EnumProperty(
        name="Model Version",
        items=[
            ('3.0', "Hunyuan 3.0", ""),
            ('3.1', "Hunyuan 3.1", ""),
        ],
        default='3.0',
    )
    job: PointerProperty(type=MixieHunyuanJobState)


class MixieHunyuanRapidProps(PropertyGroup):
    """Input properties for Hunyuan 3D Rapid mode."""

    prompt: StringProperty(name="Prompt", maxlen=200, default="")
    image: PointerProperty(type=bpy.types.Image, name="Image")
    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image. "
                    "OFF: Use uploaded image or prompt",
        default=True,
    )
    result_format: EnumProperty(
        name="Result Format",
        items=[
            ('glb', "GLB", ""),
            ('obj', "OBJ", ""),
            ('stl', "STL", ""),
            ('usdz', "USDZ", ""),
            ('fbx', "FBX", ""),
            ('mp4', "MP4", ""),
            ('gif', "GIF", ""),
        ],
        default='glb',
    )
    enable_pbr: BoolProperty(name="Enable PBR", default=False)
    enable_geometry: BoolProperty(name="Geometry Only", default=False)
    job: PointerProperty(type=MixieHunyuanJobState)


class MixieHunyuanPartProps(PropertyGroup):
    """Input properties for Hunyuan 3D Part mode."""

    export_format: EnumProperty(
        name="Export Format",
        items=[('FBX', "FBX", "")],
        default='FBX',
    )
    job: PointerProperty(type=MixieHunyuanJobState)


class MixieHunyuanTopologyProps(PropertyGroup):
    """Input properties for Hunyuan 3D Topology mode."""

    polygon_type: EnumProperty(
        name="Polygon Type",
        items=[
            ('triangle', "Triangle", ""),
            ('quadrilateral', "Quadrilateral", ""),
        ],
        default='triangle',
    )
    face_level: EnumProperty(
        name="Face Level",
        items=[
            ('high', "High", ""),
            ('medium', "Medium", ""),
            ('low', "Low", ""),
        ],
        default='medium',
    )
    post_process: BoolProperty(
        name="Post-Processing",
        description="Run GPU post-processing: fix pivot, match scale, UV unwrap, and bake textures from HP to LP",
        default=True,
    )
    job: PointerProperty(type=MixieHunyuanJobState)


class MixieHunyuanUVProps(PropertyGroup):
    """Input properties for Hunyuan 3D UV mode."""

    export_format: EnumProperty(
        name="Export Format",
        items=[('FBX', "FBX", ""), ('OBJ', "OBJ", ""), ('GLB', "GLB", "")],
        default='GLB',
    )
    job: PointerProperty(type=MixieHunyuanJobState)


# ============================================================================
# ROOT PROPERTY GROUP (attached to Scene)
# ============================================================================


class MixieHunyuanProps(PropertyGroup):
    """Root Hunyuan property group with mode selector and per-mode sub-groups."""

    active_mode: EnumProperty(
        name="Mode",
        items=[
            ('PRO', "Pro", "High-quality 3D generation"),
            ('RAPID', "Rapid", "Fast 3D generation"),
            ('PART', "Part", "Decompose into parts"),
            ('TOPOLOGY', "Topo", "AI retopology"),
            ('UV', "UV", "AI UV unwrapping"),
        ],
        default='PRO',
    )
    pro: PointerProperty(type=MixieHunyuanProProps)
    rapid: PointerProperty(type=MixieHunyuanRapidProps)
    part: PointerProperty(type=MixieHunyuanPartProps)
    topology: PointerProperty(type=MixieHunyuanTopologyProps)
    uv: PointerProperty(type=MixieHunyuanUVProps)


# ============================================================================
# REGISTRATION (dependency order: base types first)
# ============================================================================

classes = (
    MixieHunyuanMultiViewEntry,
    MixieHunyuanUploadedImage,
    MixieHunyuanJobState,
    MixieHunyuanProProps,
    MixieHunyuanRapidProps,
    MixieHunyuanPartProps,
    MixieHunyuanTopologyProps,
    MixieHunyuanUVProps,
    MixieHunyuanProps,
)


def register():
    from bpy.utils import register_class

    for cls in classes:
        try:
            register_class(cls)
        except ValueError:
            pass
    bpy.types.Scene.hunyuan = PointerProperty(type=MixieHunyuanProps)


def unregister():
    from bpy.utils import unregister_class

    try:
        del bpy.types.Scene.hunyuan
    except AttributeError:
        pass
    for cls in reversed(classes):
        try:
            unregister_class(cls)
        except RuntimeError:
            pass
