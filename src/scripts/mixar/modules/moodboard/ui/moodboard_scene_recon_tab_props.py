# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Reconstruction tab properties for the moodboard sidebar."""

from bpy.types import PropertyGroup
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
)

from .moodboard_enum_callbacks import (
    _get_scene_gen_mode_items,
    _on_model_changed,
)


class MixieMoodboardTabSceneReconProps(PropertyGroup):
    """Properties for Scene Reconstruction tab"""

    # Generation mode = catalog service of capability "scene_gen"
    # (Scene Reconstruction = scene_reconstruction / Segments to 3D =
    # scene_gen)
    mode: EnumProperty(
        name="Mode",
        description="Scene generation mode",
        items=_get_scene_gen_mode_items,
        update=_on_model_changed,
    )

    # Text prompt for scene generation (alternative to providing an image)
    prompt: StringProperty(
        name="Scene Description",
        description="Describe the scene to generate an image for reconstruction",
        default="",
        maxlen=2048,
        options={'TEXTEDIT_UPDATE'},
    )

    # Toggle between file picker (OFF) and selected moodboard image (ON)
    use_selected_image: BoolProperty(
        name="Use Selected Moodboard Image",
        description="ON: Use currently selected moodboard image. "
                    "OFF: Use uploaded image via file picker",
        default=True
    )

    # File picker image path and name
    image_path: StringProperty(
        name="Image Path",
        description="Path to the input image file",
        default="",
        subtype="FILE_PATH"
    )

    image_name: StringProperty(
        name="Image Name",
        description="Display name of the input image",
        default=""
    )

    # Pipeline parameters
    generate_mesh: BoolProperty(
        name="Generate Meshes",
        description="Generate 3D meshes per object (slower but provides actual geometry)",
        default=True,
    )

    min_mask_pixels: IntProperty(
        name="Min Object Size",
        description="Minimum segment size in pixels. Higher values filter out small objects",
        default=2000,
        min=100,
        max=50000,
    )

    mesh_postprocess: BoolProperty(
        name="Simplify Mesh",
        description="Reduce poly count via decimation and fill holes",
        default=False,
    )

    texture_baking: BoolProperty(
        name="Bake Textures",
        description="Bake textures onto mesh UVs (slower)",
        default=True,
    )

    vertex_color: BoolProperty(
        name="Vertex Colors",
        description="Use vertex colors instead of baked textures",
        default=False,
    )

    save_to_library: BoolProperty(
        name="Save to Asset Library",
        description="Automatically save imported meshes to the asset library",
        default=False,
    )

    asset_library_path: StringProperty(
        name="Asset Library Path",
        description="Directory path for the asset library",
        default="",
        subtype="DIR_PATH",
    )

    # Status properties (updated by manager during polling — SKIP_SAVE so undo
    # doesn't restore stale polling state)
    stage_name: StringProperty(
        name="Stage Name",
        description="Current pipeline stage name",
        default="",
        options={'SKIP_SAVE'},
    )

    stage_detail: StringProperty(
        name="Stage Detail",
        description="Current operation detail",
        default="",
        options={'SKIP_SAVE'},
    )

    status_text: StringProperty(
        name="Status Text",
        description="Current job status",
        default="",
        options={'SKIP_SAVE'},
    )

    elapsed_seconds: FloatProperty(
        name="Elapsed Seconds",
        description="Seconds since job started",
        default=0.0,
        min=0.0,
        options={'SKIP_SAVE'},
    )

    # Phase 2 properties
    phase: StringProperty(
        name="Phase",
        description="Current phase (scene_reconstruction/model_generation/completed)",
        default="",
        options={'SKIP_SAVE'},
    )

    total_objects: IntProperty(
        name="Total Objects",
        description="Total number of objects detected in the scene",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )

    completed_objects: IntProperty(
        name="Completed Objects",
        description="Number of objects with completed 3D models",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )

    # Result (kept for backwards compatibility)
    result_path: StringProperty(
        name="Result Path",
        description="Path to the downloaded result file",
        default="",
        options={'SKIP_SAVE'},
    )

    # Error
    error_text: StringProperty(
        name="Error Text",
        description="Error message if job failed",
        default="",
        options={'SKIP_SAVE'},
    )
