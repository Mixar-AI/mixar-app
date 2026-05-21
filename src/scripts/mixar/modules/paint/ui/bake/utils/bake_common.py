# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Common bake utilities and re-exports for the bake module.

This module serves as the main entry point for bake-related functionality,
re-exporting functions from specialized sub-modules for backward compatibility.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

BL28_HACK = True

TEMP_VCOL = "__temp__vcol__"
TEMP_EMISSION = "_TEMP_EMI_"

# =============================================================================
# Re-exports from bake_base_operator
# =============================================================================

from ..operators.bake_base_operator import BaseBakeOperator

# =============================================================================
# Re-exports from bake_scene_settings
# =============================================================================

from .bake_scene_settings import (
    get_compositor_node_tree,
    get_compositor_output_node,
    get_scene_bake_multires,
    get_scene_bake_clear,
    get_scene_render_bake_type,
    get_scene_bake_margin,
    set_scene_bake_multires,
    set_scene_bake_clear,
    set_scene_render_bake_type,
    set_scene_bake_margin,
)

# =============================================================================
# Re-exports from bake_settings_manager
# =============================================================================

from .bake_settings_manager import (
    remember_before_bake,
    prepare_bake_settings,
    recover_bake_settings,
    prepare_composite_settings,
    recover_composite_settings,
)

# =============================================================================
# Re-exports from bake_image_processing
# =============================================================================

from .bake_image_processing import (
    blur_image,
    denoise_image,
    dither_image,
    noise_blur_image,
    fxaa_image,
    get_pointiness_image_minmax_value,
    resize_image,
)

# =============================================================================
# Re-exports from bake_object_prep
# =============================================================================

from ..object_prep.bake_object_prep import (
    prepare_other_objs_colors,
    prepare_other_objs_channels,
    recover_other_objs_channels,
    get_bakeable_objects_and_meshes,
    get_duplicated_mesh_objects,
    get_merged_mesh_objects,
)

# =============================================================================
# Re-exports from bake_temp_materials
# =============================================================================

from .bake_temp_materials import (
    create_plane_on_object_mode,
    get_valid_filepath,
    put_image_to_image_atlas,
    get_temp_default_material,
    remove_temp_default_material,
    get_temp_emit_white_mat,
    remove_temp_emit_white_mat,
)

# =============================================================================
# Re-exports from bake_uv_ops
# =============================================================================

from ..operators.bake_uv_ops import (
    ACTIVE_UV_NODE,
    get_active_render_uv_node,
    add_active_render_uv_node,
    get_output_uv_names_from_geometry_nodes,
)

# =============================================================================
# Re-exports from bake_validation
# =============================================================================

from .bake_validation import (
    BAKE_PROBLEMATIC_MODIFIERS,
    JOIN_PROBLEMATIC_TEXCOORDS,
    get_problematic_modifiers,
    search_join_problematic_texcoord,
    is_there_any_missmatched_attribute_types,
    is_join_objects_problematic,
    is_object_bakeable,
)

# =============================================================================
# Re-exports from bake_vcol_utils
# =============================================================================

from .bake_vcol_utils import (
    bake_object_op,
    bake_to_vcol,
)

# =============================================================================
# Re-exports from bake_height_ops
# =============================================================================

from ..operators.bake_height_ops import (
    is_baked_normal_without_bump_needed,
    get_bake_max_height,
)

# =============================================================================
# Re-exports from bake_entity_image
# =============================================================================

from ..entity.bake_entity_image import (
    bake_entity_as_image,
)
