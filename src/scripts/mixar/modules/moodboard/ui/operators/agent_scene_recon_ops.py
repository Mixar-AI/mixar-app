# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Scene Reconstruction Operator

Simplified operator for agent-driven SAM3D scene reconstruction. Takes
all parameters as properties for direct invocation by the agent.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import compress_image_for_upload
from mixar.modules.moodboard.core.generate_progress import (
    reset_progress,
    start_progress,
)
from mixar.modules.moodboard.core.scene_recon_submission import (
    submit_recon_job as _submit_recon_job,
)

logger = get_logger(__name__)


class MIXIE_OT_agent_scene_recon(Operator):
    """Reconstruct a 3D scene from an image via agent"""

    bl_idname = "mixie.agent_scene_recon"
    bl_label = "Agent Scene Reconstruction"
    bl_description = "Reconstruct a 3D scene from an input image via agent"
    bl_options = {"REGISTER"}

    image_name: bpy.props.StringProperty(
        name="Image Name",
        description="Name of image in bpy.data.images to reconstruct from",
        default="",
    )
    generate_mesh: bpy.props.BoolProperty(
        name="Generate Mesh",
        description=(
            "Generate full GLB meshes per detected object. When off, only "
            "bounding-box placeholders are imported."
        ),
        default=True,
    )
    min_mask_pixels: bpy.props.IntProperty(
        name="Min Mask Pixels",
        description="Minimum segment size in pixels to include an object",
        default=2000,
        min=0,
    )
    mesh_postprocess: bpy.props.BoolProperty(
        name="Mesh Postprocess",
        description="Decimate and fill holes on generated meshes",
        default=True,
    )
    texture_baking: bpy.props.BoolProperty(
        name="Texture Baking",
        description="Bake textures to UVs (slower); otherwise vertex colors only",
        default=False,
    )
    vertex_color: bpy.props.BoolProperty(
        name="Vertex Color",
        description="Use vertex colors instead of baked textures",
        default=True,
    )

    def execute(self, context):
        scene = context.scene

        if not self.image_name:
            self.report({"ERROR"}, "image_name is required")
            return {"CANCELLED"}

        img = bpy.data.images.get(self.image_name)
        if not img or not img.has_data:
            self.report(
                {"ERROR"},
                f"Image '{self.image_name}' not found or has no data",
            )
            return {"CANCELLED"}

        if (
            hasattr(scene, "mixie_scene_recon_is_generating")
            and scene.mixie_scene_recon_is_generating
        ):
            self.report({"WARNING"}, "Scene reconstruction already in progress")
            return {"CANCELLED"}

        # The submission helper writes status/error onto the sidebar tab; reuse
        # the existing one so the user-facing panel reflects the agent's run.
        sidebar_tab = None
        if hasattr(scene, "mixie_moodboard_sidebar"):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, "tab_scene_recon"):
                sidebar_tab = sidebar.tab_scene_recon
        if sidebar_tab is None:
            self.report({"ERROR"}, "Scene reconstruction properties not initialised")
            return {"CANCELLED"}

        try:
            image_bytes = compress_image_for_upload(img)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to compress image: {e}")
            return {"CANCELLED"}

        start_progress("scene_recon")
        success = _submit_recon_job(
            scene,
            sidebar_tab,
            image_bytes,
            generate_mesh=self.generate_mesh,
            min_mask_pixels=self.min_mask_pixels,
            mesh_postprocess=self.mesh_postprocess,
            texture_baking=self.texture_baking,
            vertex_color=self.vertex_color,
        )

        if not success:
            reset_progress("scene_recon")
            self.report({"WARNING"}, "Failed to submit reconstruction job")
            return {"CANCELLED"}

        self.report({"INFO"}, "Scene reconstruction started...")
        return {"FINISHED"}


classes = (MIXIE_OT_agent_scene_recon,)
