# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen Experimental tab properties for the moodboard sidebar.

Stores the user inputs (image source + min mask pixels), transient processing
state (job_id, error, processing flag), the detected label objects returned by
the backend ``/scene-reconstruction/jobs`` endpoint (labels_only mode), and the
Step 2 batch-image-generation settings + per-object generation status.
"""

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .moodboard_enum_callbacks import (
    _get_imagegen_model_items,
    _get_imagegen_aspect_ratio_items,
    _get_imagegen_resolution_items,
)

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _on_active_label_changed(self, context):
    """Select linked moodboard image + HP/LP meshes when active label changes."""
    tab = self
    if tab.active_label_index < 0 or tab.active_label_index >= len(tab.objects):
        return

    active_obj = tab.objects[tab.active_label_index]
    chain_id = active_obj.chain_id
    if not chain_id:
        return

    scene = context.scene

    # Deselect all moodboard images, select only matching chain_id
    try:
        for item in scene.mixie_moodboard_images:
            item.selected = (item.chain_id == chain_id)
    except Exception as e:
        logger.debug("[SceneGenExp] Failed to select moodboard image: %s", e)

    # Deselect only chain_id-tagged viewport objects, select HP+LP matching chain_id
    try:
        import bpy
        for obj in bpy.data.objects:
            if obj.type != 'MESH' or "mixar_chain_id" not in obj:
                continue
            obj.select_set(obj["mixar_chain_id"] == chain_id)
    except Exception as e:
        logger.debug("[SceneGenExp] Failed to select viewport objects: %s", e)


# Per-object generation status values
_GEN_STATUS_ITEMS = [
    ("pending", "Pending", "Not yet generated"),
    ("generating", "Generating", "Generation in progress"),
    ("completed", "Completed", "Successfully generated"),
    ("failed", "Failed", "Generation failed"),
]


class MixieSceneGenExpBBox(PropertyGroup):
    """2D bounding box in input-image pixel coordinates."""

    x: IntProperty(name="X", default=0)
    y: IntProperty(name="Y", default=0)
    width: IntProperty(name="Width", default=0)
    height: IntProperty(name="Height", default=0)


class MixieSceneGenExpLabelObject(PropertyGroup):
    """A single detected object returned by the labels endpoint."""

    label: StringProperty(name="Label", default="")
    category: StringProperty(name="Category", default="")
    confidence: FloatProperty(name="Confidence", default=0.0, min=0.0, max=1.0)
    bbox: PointerProperty(type=MixieSceneGenExpBBox, name="BBox")

    # 3D spatial metadata from scene reconstruction (stored for future use)
    center: FloatVectorProperty(name="Center", size=3, default=(0.0, 0.0, 0.0))
    dimensions: FloatVectorProperty(name="Dimensions", size=3, default=(0.0, 0.0, 0.0))
    rotation: FloatVectorProperty(name="Rotation", size=4, default=(1.0, 0.0, 0.0, 0.0))
    obj_scale: FloatProperty(name="Scale", default=1.0)

    # Pipeline chain ID (assigned at Step 1, propagated through Steps 2-4)
    chain_id: StringProperty(name="Chain ID", default="")

    # Step 2 state
    selected: BoolProperty(
        name="Include in Image Generation",
        description="If ON, an image will be generated for this object in Step 2",
        default=True,
    )
    gen_status: EnumProperty(
        name="Generation Status",
        items=_GEN_STATUS_ITEMS,
        default="pending",
        options={'SKIP_SAVE'},
    )
    gen_error: StringProperty(
        name="Generation Error",
        default="",
        options={'SKIP_SAVE'},
    )


class MixieMoodboardTabSceneGenExpProps(PropertyGroup):
    """Properties for the 'Scene Gen Experimental' tab."""

    active_label_index: IntProperty(
        name="Active Label Index",
        default=0,
        update=_on_active_label_changed,
    )
    rename_allowed: BoolProperty(
        name="Rename Allowed",
        default=True,
        options={'SKIP_SAVE'},
    )

    # Toggle between uploaded image (OFF) and selected moodboard image (ON).
    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image. "
                    "OFF: Use uploaded image",
        default=True,
    )

    # Uploaded image (used when toggle is OFF). Matches the image_to_3d pattern.
    reference_image: PointerProperty(
        type=bpy.types.Image,
        name="Input Image",
        description="Uploaded image for label extraction (used when toggle is OFF)",
    )

    # Exposed parameter (others hidden — use backend defaults).
    min_mask_pixels: IntProperty(
        name="Min Object Size",
        description="Minimum segment size in pixels. Higher values filter out small objects",
        default=2000,
        min=100,
        max=50000,
    )

    # Transient state (SKIP_SAVE so a .blend reload doesn't restore stale flags).
    job_id: StringProperty(
        name="Job ID",
        description="Active labels job ID",
        default="",
        options={'SKIP_SAVE'},
    )

    error_text: StringProperty(
        name="Error",
        description="Last error message",
        default="",
        options={'SKIP_SAVE'},
    )

    stage_detail: StringProperty(
        name="Stage Detail",
        description="Current pipeline stage detail (from backend poll)",
        default="",
        options={'SKIP_SAVE'},
    )

    has_result: BoolProperty(
        name="Has Result",
        description="Whether a labels result is available",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Detected objects. Populated on successful completion.
    objects: CollectionProperty(
        type=MixieSceneGenExpLabelObject,
        name="Detected Objects",
        description="Objects detected by the labels endpoint",
    )

    # ------------------------------------------------------------------
    # Step 2: batch image generation
    # ------------------------------------------------------------------

    imagegen_model: EnumProperty(
        name="Model",
        description="Image generation model to use for all objects in this batch",
        items=_get_imagegen_model_items,
    )
    imagegen_aspect_ratio: EnumProperty(
        name="Aspect Ratio",
        description="Aspect ratio to use for all generated images in this batch",
        items=_get_imagegen_aspect_ratio_items,
    )
    imagegen_resolution: EnumProperty(
        name="Resolution",
        description="Resolution to use for all generated images in this batch",
        items=_get_imagegen_resolution_items,
    )

    gen_in_progress: BoolProperty(
        name="Generation In Progress",
        description="Whether Step 2 batch image generation is running",
        default=False,
        options={'SKIP_SAVE'},
    )
    gen_total_count: IntProperty(
        name="Generation Total",
        default=0,
        options={'SKIP_SAVE'},
    )
    gen_completed_count: IntProperty(
        name="Generation Completed",
        default=0,
        options={'SKIP_SAVE'},
    )
    gen_failed_count: IntProperty(
        name="Generation Failed",
        default=0,
        options={'SKIP_SAVE'},
    )

    # ------------------------------------------------------------------
    # Step 3: HP (Image-to-3D Pro) generation settings
    # ------------------------------------------------------------------

    hp_generate_type: EnumProperty(
        name="Generate Type",
        items=[
            ('Normal', "Normal", "Standard generation"),
            ('LowPoly', "LowPoly", "Low polygon output"),
        ],
        default='Normal',
    )
    hp_model_version: EnumProperty(
        name="Model Version",
        items=[
            ('3.0', "3.0", ""),
            ('3.1', "3.1", ""),
        ],
        default='3.0',
    )
    hp_enable_pbr: BoolProperty(
        name="Enable PBR",
        description="Generate PBR textures",
        default=False,
    )
    hp_face_count: IntProperty(
        name="Face Count",
        default=500000,
        min=40000,
        max=1500000,
    )
    hp_polygon_type: EnumProperty(
        name="Polygon Type",
        items=[
            ('triangle', "Triangle", ""),
            ('quadrilateral', "Quadrilateral", ""),
        ],
        default='triangle',
    )
    hp_in_progress: BoolProperty(
        name="HP In Progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # ------------------------------------------------------------------
    # Step 4: LP (Retopology) settings
    # ------------------------------------------------------------------

    lp_polygon_type: EnumProperty(
        name="Polygon Type",
        items=[
            ('triangle', "Triangle", ""),
            ('quadrilateral', "Quadrilateral", ""),
        ],
        default='triangle',
    )
    lp_face_level: EnumProperty(
        name="Face Level",
        items=[
            ('high', "High", ""),
            ('medium', "Medium", ""),
            ('low', "Low", ""),
        ],
        default='medium',
    )
    lp_post_process: BoolProperty(
        name="Post-Processing",
        description="Run GPU post-processing: fix pivot, match scale, UV unwrap, bake textures",
        default=True,
    )
    lp_in_progress: BoolProperty(
        name="LP In Progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # ------------------------------------------------------------------
    # Step 5: Place in Scene
    # ------------------------------------------------------------------

    place_mesh_type: EnumProperty(
        name="Mesh Type",
        description="Which mesh to use for scene placement",
        items=[
            ('LP', "Low Poly", "Use LP mesh (falls back to HP if LP not available)"),
            ('HP', "High Poly", "Use HP mesh directly (skip Step 4)"),
        ],
        default='LP',
    )


# Classes to register (order matters: referenced classes first)
classes = (
    MixieSceneGenExpBBox,
    MixieSceneGenExpLabelObject,
    MixieMoodboardTabSceneGenExpProps,
)
