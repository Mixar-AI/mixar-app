# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Tab Property Definitions

PropertyGroup classes for sidebar tabs: ImageGen, Lookdev, Lookdev360,
Image to 3D, Scene Reconstruction, UV Unwrap, Retopology, Segmentation,
and the parent sidebar container.
"""

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    PointerProperty,
    CollectionProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
)

from .moodboard_scene_recon_tab_props import MixieMoodboardTabSceneReconProps  # noqa: F401
from .moodboard_catalog_tab_props import (  # noqa: F401
    MixieMoodboardTabAIRenderProps,
    MixieMoodboardTabAnimateProps,
    MixieMoodboardTabRetopologyProps,
    MixieMoodboardTabUVUnwrapProps,
)
# Scene Gen Experimental disabled — PropertyGroups intentionally not imported/registered.
# from .moodboard_scene_gen_exp_tab_props import (  # noqa: F401
#     MixieSceneGenExpBBox,
#     MixieSceneGenExpLabelObject,
#     MixieMoodboardTabSceneGenExpProps,
# )

from .moodboard_enum_callbacks import (
    _get_image_gen_mode_items,
    _get_imagegen_model_items,
    _get_imagegen_style_items,
    _get_imagegen_aspect_ratio_items,
    _get_imagegen_resolution_items,
    _on_model_changed,
    _get_model_3d_items,  # noqa: F401 — legacy fallback, kept importable
    _get_model_gen_mode_items,
    _get_model_gen_model_items,
    _get_texture_gen_mode_items,
    _get_texture_gen_model_items,
    _get_mesh_segment_mode_items,
    _get_mesh_segment_model_items,
)


class MixieMoodboardTabLookdev360Props(PropertyGroup):
    """Properties for the Texture Gen (Lookdev360) tab"""

    # Generation mode = catalog service of capability "texture_gen"
    # (PBR Textures / Texture Edit / Procedural Material)
    mode: EnumProperty(
        name="Mode",
        description="Texture generation mode",
        items=_get_texture_gen_mode_items,
        update=_on_model_changed,
    )

    # Dynamic model enum — models of the selected mode (catalog), falling
    # back to the single legacy hunyuan-pbr model offline.
    model: EnumProperty(
        name="Model",
        description="AI model for texture generation",
        items=_get_texture_gen_model_items,
        update=_on_model_changed,
    )

    prompt: StringProperty(
        name="Prompt",
        description="Description for PBR texture generation",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    image_type: EnumProperty(
        name="Image Type",
        description="Type of image input for generation",
        items=[
            ('STYLE', "Style", "Style transfer image - applies artistic style to the generated textures", 0),
            ('REFERENCE', "Reference", "Reference image - directly drives texture generation (prompt ignored)", 1),
        ],
        default='STYLE'
    )

    style_only: BoolProperty(
        name="Use Image Style Only",
        description="When enabled, only the image's artistic style is transferred "
                    "(prompt still applies). When disabled, the image directly "
                    "drives texture generation",
        default=False
    )

    resolution: EnumProperty(
        name="Resolution",
        description="Output texture resolution in pixels",
        items=[
            ('512', "512", "512px - Preview/draft quality", 0),
            ('1024', "1024", "1024px - Standard quality", 1),
            ('2048', "2048", "2048px - High quality", 2),
        ],
        default='1024'
    )

    # Reference image (max 1) - stored as pointer to Image
    reference_image: PointerProperty(
        type=bpy.types.Image,
        name="Reference Image",
        description="Style reference image for texture generation"
    )

    has_applied_materials: BoolProperty(
        name="Has Applied Materials",
        description="Whether materials have been applied (for restore button)",
        default=False
    )

    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image. "
                    "OFF: Use uploaded image",
        default=True
    )


class MixieMoodboardTabLookdevProps(PropertyGroup):
    """Properties for Lookdev tab - uses generate-from-depth API"""

    prompt: StringProperty(
        name="Prompt",
        description="Description for material/texture generation",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    fast_mode: BoolProperty(
        name="Fast Mode",
        description="Enable fast depth map generation (lower quality, ~4x faster)",
        default=False
    )


class MixieMoodboardReferenceImage(PropertyGroup):
    """Reference image for ImageGen - stores direct image pointer"""

    image: PointerProperty(
        type=bpy.types.Image,
        name="Image",
        description="Direct reference to the image (preferred over moodboard_index)"
    )

    moodboard_index: IntProperty(
        name="Moodboard Index",
        description="Index into scene.mixie_moodboard_images (for C++ UI display)",
        default=-1
    )

    # Cached display info (updated when image is added)
    display_name: StringProperty(
        name="Display Name",
        description="Image name for display",
        default=""
    )

    display_resolution: StringProperty(
        name="Display Resolution",
        description="Resolution string for display (e.g., '1024x768')",
        default=""
    )

    display_path: StringProperty(
        name="Display Path",
        description="File path for display",
        default=""
    )


class MixieMoodboardTabImageGenProps(PropertyGroup):
    """Properties for ImageGen tab"""

    # Generation mode = catalog service of capability "image_gen"
    # (Text to Image = image_gen / From Blockout = depth_to_image)
    mode: EnumProperty(
        name="Mode",
        description="Image generation mode",
        items=_get_image_gen_mode_items,
        update=_on_model_changed,
    )

    prompt: StringProperty(
        name="Prompt",
        description="Description for image generation",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    # Dynamic enum properties from cache
    model: EnumProperty(
        name="Model",
        description="AI model for image generation",
        items=_get_imagegen_model_items,
        update=_on_model_changed,
    )

    style: EnumProperty(
        name="Style",
        description="Style preset for image generation",
        items=_get_imagegen_style_items,
    )

    aspect_ratio: EnumProperty(
        name="Aspect Ratio",
        description="Aspect ratio for generated images",
        items=_get_imagegen_aspect_ratio_items,
    )

    resolution: EnumProperty(
        name="Resolution",
        description="Output resolution for generated images",
        items=_get_imagegen_resolution_items,
    )

    # Toggle between uploaded images (OFF) and selected moodboard images (ON)
    use_reference_images: BoolProperty(
        name="Use Selected Moodboard Images",
        description="ON: Use currently selected moodboard images as references. "
                    "OFF: Use images you've added via the + button",
        default=True
    )

    # Collection of uploaded reference images added via the + button (used when toggle is OFF)
    reference_images: CollectionProperty(
        type=MixieMoodboardReferenceImage,
        name="Uploaded Reference Images",
        description="Images added via the + button for generation (used when toggle is OFF)"
    )


class MixieMoodboardTabMeshSegmentProps(PropertyGroup):
    """Properties for Mesh Segment tab"""

    # Generation mode = catalog service of capability "mesh_segmentation"
    # (Mesh Segmentation = mesh_segment / Part Segmentation = hunyuan_part)
    mode: EnumProperty(
        name="Mode",
        description="Mesh segmentation mode",
        items=_get_mesh_segment_mode_items,
        update=_on_model_changed,
    )

    model: EnumProperty(
        name="Model",
        description="AI model for mesh segmentation",
        items=_get_mesh_segment_model_items,
        update=_on_model_changed,
    )

    prompt: StringProperty(
        name="Prompt",
        description="Description of what to segment (e.g., 'head, torso, arms, legs')",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    expected_parts: StringProperty(
        name="Expected Parts",
        description="Expected number or description of parts",
        default="",
        maxlen=256
    )

    is_processing: BoolProperty(
        name="Is Processing",
        description="Whether segmentation is currently in progress",
        default=False,
        options={'SKIP_SAVE'},
    )


class MixieMoodboardTabImageTo3DProps(PropertyGroup):
    """Properties for the Model Gen (Image to 3D) tab"""

    prompt: StringProperty(
        name="Prompt",
        description="Description for 3D model generation from image (optional)",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    # Generation mode = catalog service of capability "model_gen"
    # (Image to 3D / Image to 3D Pro / Rapid 3D)
    mode: EnumProperty(
        name="Mode",
        description="3D generation mode",
        items=_get_model_gen_mode_items,
        update=_on_model_changed,
    )

    # Toggle between uploaded image (OFF) and selected moodboard image (ON)
    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image. "
                    "OFF: Use uploaded image",
        default=True
    )

    # Input image - stored as pointer to Image (used when toggle is OFF)
    reference_image: PointerProperty(
        type=bpy.types.Image,
        name="Input Image",
        description="Uploaded image for 3D model generation (used when toggle is OFF)"
    )

    # Dynamic model enum — models of the selected mode (catalog), falling
    # back to the legacy model_3d cache when the catalog isn't loaded.
    model: EnumProperty(
        name="Model",
        description="AI model for 3D generation",
        items=_get_model_gen_model_items,
        update=_on_model_changed,
    )


class MixieMoodboardTabSegmentTo3DProps(PropertyGroup):
    """Properties for Segment to 3D tab"""

    selected_image_index: IntProperty(
        name="Selected Image Index",
        description="Index of selected moodboard image with segments",
        default=-1
    )

    selected_image_name: StringProperty(
        name="Selected Image Name",
        description="Name of the selected image (for display)",
        default=""
    )

    active_segment_count: IntProperty(
        name="Active Segment Count",
        description="Number of active segments selected",
        default=0,
        min=0
    )


class MixieMoodboardSidebarProperties(PropertyGroup):
    """Properties for moodboard sidebar state.

    Stage 3 note: the legacy ``active_tab`` / ``imagegen_subtab`` /
    ``segmentation_subtab`` enums (which drove the old single-panel tab
    strip) were removed — the sidebar is native N-panels now (one per
    catalog capability, see ``moodboard_sidebar_panels.py``) and tab
    switching goes through ``region.active_panel_category``.
    ``image_to_3d_subtab`` survives for the Model Gen tab's
    catalog-not-loaded fallback UI (Basic/Pro subtabs).
    """

    image_to_3d_subtab: EnumProperty(
        name="Image to 3D Subtab",
        items=[
            ('BASIC', "Basic", "Standard image-to-3D generation", 0),
            ('RAPID', "Rapid", "Fast 3D generation with Hunyuan Rapid", 1),
            ('PRO', "Pro", "High-quality 3D generation with Hunyuan Pro", 2),
        ],
        default='BASIC'
    )

    # Nested property groups for each tab
    tab_lookdev360: PointerProperty(
        type=MixieMoodboardTabLookdev360Props,
        name="Lookdev360 Tab",
        description="Properties for Lookdev360 tab"
    )

    tab_lookdev: PointerProperty(
        type=MixieMoodboardTabLookdevProps,
        name="Lookdev Tab",
        description="Properties for Lookdev tab"
    )

    tab_imagegen: PointerProperty(
        type=MixieMoodboardTabImageGenProps,
        name="ImageGen Tab",
        description="Properties for ImageGen tab"
    )

    tab_ai_render: PointerProperty(
        type=MixieMoodboardTabAIRenderProps,
        name="AI Render Tab",
        description="Properties for AI Render tab"
    )

    tab_mesh_segment: PointerProperty(
        type=MixieMoodboardTabMeshSegmentProps,
        name="Mesh Segment Tab",
        description="Properties for Mesh Segment tab"
    )

    tab_image_to_3d: PointerProperty(
        type=MixieMoodboardTabImageTo3DProps,
        name="Image to 3D Tab",
        description="Properties for Image to 3D tab"
    )

    tab_segment_to_3d: PointerProperty(
        type=MixieMoodboardTabSegmentTo3DProps,
        name="Segment to 3D Tab",
        description="Properties for Segment to 3D tab"
    )

    tab_scene_recon: PointerProperty(
        type=MixieMoodboardTabSceneReconProps,
        name="Scene Recon Tab",
        description="Properties for Scene Reconstruction tab"
    )

    tab_retopology: PointerProperty(
        type=MixieMoodboardTabRetopologyProps,
        name="Retopology Tab",
        description="Properties for Retopology tab"
    )

    tab_uv_unwrap: PointerProperty(
        type=MixieMoodboardTabUVUnwrapProps,
        name="UV Unwrap Tab",
        description="Properties for UV Unwrap tab"
    )

    tab_animate: PointerProperty(
        type=MixieMoodboardTabAnimateProps,
        name="Animate Tab",
        description="Properties for Animate tab"
    )

    # Scene Gen Experimental disabled — pointer intentionally not registered.
    # tab_scene_gen_exp: PointerProperty(
    #     type=MixieMoodboardTabSceneGenExpProps,
    #     name="Scene Gen Experimental Tab",
    #     description="Properties for Scene Gen Experimental tab"
    # )
