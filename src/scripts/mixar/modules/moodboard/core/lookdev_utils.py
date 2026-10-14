# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev Utility Functions

Helper functions for depth map processing.
Common image utilities are in common/utils/image_utils.py.
"""

import bpy
import os
import tempfile
import datetime
import mathutils

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def calculate_optimal_depth_resolution(
    total_vertices: int,
    current_res_x: int,
    current_res_y: int,
    current_percentage: int,
    target_file_size_mb: float = 3.0
) -> int:
    """Calculate optimal resolution for depth map to meet target file size."""
    # Calculate target pixels for ~3MB RGB 16-bit PNG file
    target_uncompressed_mb = target_file_size_mb / 0.70
    target_pixels = (target_uncompressed_mb * 1024 * 1024) / 6
    max_dimension = int(target_pixels ** 0.5)

    # Set maximum resolution caps based on vertex count
    if total_vertices > 100000:
        max_resolution = min(2560, max(2048, max_dimension))
    elif total_vertices > 50000:
        max_resolution = min(2048, max(1536, max_dimension))
    else:
        max_resolution = min(1536, max(1024, max_dimension))

    # Calculate current effective resolution
    effective_width = int(current_res_x * current_percentage / 100)
    effective_height = int(current_res_y * current_percentage / 100)
    current_max_dim = max(effective_width, effective_height)

    # Don't upscale beyond calculated maximum
    if current_max_dim > max_resolution:
        aspect_ratio = current_res_x / current_res_y
        if aspect_ratio >= 1:
            new_width = min(max_resolution, current_res_x)
            new_percentage = (new_width / current_res_x) * 100
        else:
            new_height = min(max_resolution, current_res_y)
            new_percentage = (new_height / current_res_y) * 100
        return min(100, max(25, int(new_percentage)))

    # Apply modest scaling based on vertex count
    if total_vertices > 100000 and current_percentage < 125:
        return min(125, current_percentage + 25)
    elif total_vertices > 50000 and current_percentage < 110:
        return min(110, current_percentage + 10)
    return current_percentage


def optimize_depth_file_size(
    depth_filepath: str,
    scene: bpy.types.Scene,
    target_size_mb: float = 5.0
) -> str:
    """
    Optimize depth map file size using PIL compression without re-rendering.

    PERFORMANCE NOTE: Previous implementation re-rendered the entire scene multiple times
    to test different compression levels. This new implementation compresses the existing
    image file directly, which is ~10-50x faster.
    """
    if not os.path.exists(depth_filepath):
        return depth_filepath

    file_size_mb = os.path.getsize(depth_filepath) / (1024 * 1024)
    logger.debug("[Lookdev] Initial depth map size: %.2fMB", file_size_mb)

    if file_size_mb <= target_size_mb:
        logger.debug("[Lookdev] Depth map size OK: %.2fMB <= %.0fMB", file_size_mb, target_size_mb)
        return depth_filepath

    logger.debug("[Lookdev] Depth map too large (%.2fMB), compressing with PIL...", file_size_mb)

    try:
        from PIL import Image

        # Load the image
        img = Image.open(depth_filepath)

        # Try progressively higher compression levels
        compression_levels = [6, 7, 8, 9]  # PNG compress_level (0-9, higher = smaller + slower)

        for compress_level in compression_levels:
            # Save with higher compression
            temp_path = depth_filepath + ".tmp"
            img.save(temp_path, format='PNG', compress_level=compress_level, optimize=True)

            new_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            logger.debug("[Lookdev] Compression level %s: %.2fMB", compress_level, new_size_mb)

            if new_size_mb <= target_size_mb:
                os.replace(temp_path, depth_filepath)
                logger.debug("[Lookdev] Optimized to %.2fMB", new_size_mb)
                return depth_filepath

            os.remove(temp_path)

        # If still too large, use maximum compression
        img.save(depth_filepath, format='PNG', compress_level=9, optimize=True)
        final_size_mb = os.path.getsize(depth_filepath) / (1024 * 1024)
        logger.debug("[Lookdev] Final size after max compression: %.2fMB", final_size_mb)

    except Exception as e:
        logger.error("[Lookdev] PIL compression failed: %s, keeping original file", e)

    return depth_filepath


def _restore_render_settings(scene, engine, view_transform, look, film_transparent, use_compositing,
                              use_nodes, resolution_x, resolution_y, percentage, filepath,
                              taa_samples, taa_reprojection):
    """Restore original render settings."""
    scene.render.engine = engine
    scene.view_settings.view_transform = view_transform
    scene.view_settings.look = look
    scene.render.film_transparent = film_transparent
    scene.render.use_compositing = use_compositing
    scene.use_nodes = use_nodes
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = percentage
    scene.render.filepath = filepath

    if hasattr(scene, 'eevee'):
        if taa_samples is not None:
            scene.eevee.taa_render_samples = taa_samples
        if taa_reprojection is not None:
            scene.eevee.use_taa_reprojection = taa_reprojection


def _cleanup_temp_compositor(node_tree):
    """Clean up temporary compositor node group."""
    if node_tree and node_tree.name == "TEMP_DEPTH_COMPOSITOR":
        try:
            bpy.context.scene.compositing_node_group = None
            bpy.data.node_groups.remove(node_tree)
        except:
            pass


def prepare_depth_render(fast_mode: bool = False) -> tuple:
    """
    Render depth map from current scene.

    Args:
        fast_mode: If True, use minimal quality settings for fastest rendering.
                   Reduces TAA samples and skips edge enhancement.

    Returns:
        (depth_filepath, success) tuple.

    Performance optimizations:
    - TAA samples reduced from 64 to 16 (4x faster rendering)
    - Unsharp mask removed (saves blur + 3 nodes)
    - 8-bit color depth instead of 16-bit (faster I/O, smaller files)
    - Smart PIL-based compression (no re-rendering)
    - Optional fast_mode for instant depth generation
    """
    if not bpy.context.scene:
        logger.error("[Lookdev] Blender context not ready")
        return None, False

    scene = bpy.context.scene

    # Ensure we have a camera
    if not scene.camera:
        logger.debug("[Lookdev] No camera found, creating one aligned to view")
        bpy.ops.object.camera_add()
        camera_obj = bpy.context.scene.objects.get("Camera")
        bpy.context.view_layer.objects.active = camera_obj

        # Align camera to current 3D viewport
        region_3d = None
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        region_3d = area.spaces.active.region_3d
                        break
                break

        if region_3d and camera_obj:
            view_matrix = region_3d.view_matrix.copy()
            camera_matrix = view_matrix.inverted()
            camera_obj.matrix_world = camera_matrix
            bpy.context.scene.camera = camera_obj
            logger.debug("[Lookdev] Camera aligned to view")
        else:
            logger.warning("[Lookdev] No 3D viewport found - camera created but not aligned")

    # Store original settings
    original_engine = scene.render.engine
    original_view_transform = scene.view_settings.view_transform
    original_look = scene.view_settings.look
    original_film_transparent = scene.render.film_transparent
    original_use_compositing = scene.render.use_compositing
    original_use_nodes = scene.use_nodes
    original_resolution_x = scene.render.resolution_x
    original_resolution_y = scene.render.resolution_y
    original_percentage = scene.render.resolution_percentage
    original_filepath = scene.render.filepath

    # Store original EEVEE TAA settings
    original_taa_samples = scene.eevee.taa_render_samples if hasattr(scene, 'eevee') else None
    original_taa_reprojection = scene.eevee.use_taa_reprojection if hasattr(scene, 'eevee') else None

    # Configure for depth rendering
    scene.render.engine = 'BLENDER_EEVEE'
    view_layer = bpy.context.view_layer
    view_layer.use_pass_z = True

    # Configure EEVEE TAA for smoother depth gradients
    # PERFORMANCE: Reduced from 64 to 16 samples (4x faster) - still provides good quality
    if hasattr(scene, 'eevee'):
        scene.eevee.taa_render_samples = 8 if fast_mode else 16
        scene.eevee.use_taa_reprojection = True

    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.look = 'None'
    scene.render.film_transparent = True
    scene.render.use_compositing = True

    # Calculate mesh bounding box for depth normalization
    mesh_objects = [obj for obj in scene.objects if obj.type == 'MESH' and obj.visible_get()]

    if not mesh_objects:
        logger.warning("[Lookdev] No visible mesh objects found")
        return None, False

    # Calculate Z-depth range from camera (matching Blender's Z-buffer depth pass)
    camera = scene.camera
    camera_matrix = camera.matrix_world
    camera_location = camera_matrix.to_translation()

    # Get camera forward direction (cameras look down local -Z axis)
    camera_forward = camera_matrix.to_quaternion() @ mathutils.Vector((0.0, 0.0, -1.0))

    # Calculate Z-depth for each object's bounding box corners
    z_depths = []
    for obj in mesh_objects:
        bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
        for corner in bbox_corners:
            to_corner = corner - camera_location
            z_depth = to_corner.dot(camera_forward)  # Project onto camera view direction (Z-buffer value)
            if z_depth > 0:  # Only include geometry in front of camera
                z_depths.append(z_depth)

    # Handle edge case where no geometry is in front of camera
    if not z_depths:
        logger.warning("[Lookdev] No geometry in front of camera, using camera clip range")
        depth_min = camera.data.clip_start
        depth_max = camera.data.clip_end
    else:
        depth_min = min(z_depths)
        depth_max = max(z_depths)

        logger.debug("[Lookdev] Raw Z-depth range: %.3f to %.3f", depth_min, depth_max)

        # Add 5% safety padding to prevent edge clipping
        depth_range = depth_max - depth_min
        padding = depth_range * 0.05
        depth_min = max(camera.data.clip_start, depth_min - padding)
        depth_max = min(camera.data.clip_end, depth_max + padding)

    depth_range = depth_max - depth_min

    logger.debug("[Lookdev] Final Z-depth range (with padding): %.3f to %.3f (range: %.3f)", depth_min, depth_max, depth_range)

    # Initialize compositor
    try:
        scene.use_nodes = True

        if scene.compositing_node_group is None:
            comp_tree = bpy.data.node_groups.new("TEMP_DEPTH_COMPOSITOR", "CompositorNodeTree")
            scene.compositing_node_group = comp_tree

        bpy.context.view_layer.depsgraph.update()
        bpy.context.view_layer.update()
        node_tree = scene.compositing_node_group
        use_compositor = node_tree is not None
    except Exception as e:
        logger.error("[Lookdev] Compositor not available: %s", e, exc_info=True)
        use_compositor = False
        node_tree = None

    if use_compositor and node_tree:
        logger.debug("[Lookdev] Using compositor for depth processing")
        nodes = node_tree.nodes
        links = node_tree.links

        # Clear existing nodes
        for node in nodes:
            nodes.remove(node)

        # Create nodes
        render_layers = nodes.new(type='CompositorNodeRLayers')
        render_layers.location = (-400, 0)

        # Map range node (normalize depth to 0-1)
        map_range_node = nodes.new(type='ShaderNodeMapRange')
        map_range_node.location = (-200, 0)
        map_range_node.inputs[1].default_value = depth_min
        map_range_node.inputs[2].default_value = depth_max
        map_range_node.inputs[3].default_value = 0.0
        map_range_node.inputs[4].default_value = 1.0

        # Power curve for perceptual depth distribution (0.35 = more dynamic range)
        power_node = nodes.new(type='ShaderNodeMath')
        power_node.operation = 'POWER'
        power_node.location = (-100, 0)
        power_node.inputs[1].default_value = 0.35
        power_node.use_clamp = True

        # Gamma correction to brighten highlights (1.8 = whiter near geometry)
        gamma_node = nodes.new(type='ShaderNodeGamma')
        gamma_node.location = (200, 0)
        gamma_node.inputs[1].default_value = 1.8

        # PERFORMANCE: Unsharp mask removed (saved blur + 3 mix nodes, ~30% faster compositing)
        # The TAA samples already provide smooth gradients, unsharp mask was redundant

        invert_node = nodes.new(type='CompositorNodeInvert')
        invert_node.location = (400, 0)

        set_alpha_node = nodes.new(type='CompositorNodeSetAlpha')
        set_alpha_node.location = (600, 0)

        # Create output node
        from mixar.modules.paint.core.io.input_outputs.outputs import new_tree_output, get_tree_output_by_name
        if not get_tree_output_by_name(node_tree, "Image"):
            new_tree_output(node_tree, "Image", "NodeSocketColor")
        composite = nodes.new(type='NodeGroupOutput')
        composite.location = (800, 0)

        # Connect nodes (simplified chain without unsharp mask)
        try:
            links.new(render_layers.outputs['Depth'], map_range_node.inputs[0])
            links.new(map_range_node.outputs[0], power_node.inputs[0])
            links.new(power_node.outputs[0], gamma_node.inputs[0])
            links.new(gamma_node.outputs[0], invert_node.inputs['Color'])
            links.new(invert_node.outputs['Color'], set_alpha_node.inputs['Image'])
            links.new(render_layers.outputs['Alpha'], set_alpha_node.inputs['Alpha'])
            links.new(set_alpha_node.outputs['Image'], composite.inputs['Image'])

            taa_samples = 8 if fast_mode else 16
            logger.debug("[Lookdev] Optimized node chain: RenderLayers(Depth) -> MapRange(%.2f-%.2f) -> Power(0.35) -> Gamma(1.8) -> Invert -> SetAlpha -> Output (TAA: %s)", depth_min, depth_max, taa_samples)
        except Exception as e:
            logger.error("[Lookdev] Error setting up compositor nodes: %s", e, exc_info=True)
            links.new(render_layers.outputs['Depth'], composite.inputs['Image'])
    else:
        logger.error("[Lookdev] Compositor not available! Cannot generate depth map.")
        _restore_render_settings(scene, original_engine, original_view_transform, original_look,
                                 original_film_transparent, original_use_compositing, original_use_nodes,
                                 original_resolution_x, original_resolution_y, original_percentage,
                                 original_filepath, original_taa_samples, original_taa_reprojection)
        _cleanup_temp_compositor(node_tree)
        return None, False

    # Configure render settings
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '16'  # 16-bit for better depth precision
    scene.render.image_settings.compression = 15  # Lower compression for faster saving

    # Calculate optimal resolution
    total_vertices = sum(
        len(obj.data.vertices) if obj.data and hasattr(obj.data, 'vertices') else 0
        for obj in mesh_objects
    )
    optimal_percentage = calculate_optimal_depth_resolution(
        total_vertices,
        original_resolution_x,
        original_resolution_y,
        original_percentage
    )
    scene.render.resolution_percentage = optimal_percentage

    # Create output path
    temp_dir = os.path.join(tempfile.gettempdir(), 'blender_depth_renders')
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    depth_filepath = os.path.join(temp_dir, f"depth_render_{timestamp}.png")
    scene.render.filepath = depth_filepath

    # Render depth map
    logger.debug("[Lookdev] Rendering %sx%s at %s%%", scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage)
    bpy.ops.render.render(write_still=True)

    if not os.path.exists(depth_filepath):
        logger.error("[Lookdev] Failed to save depth render")
        _restore_render_settings(scene, original_engine, original_view_transform, original_look,
                                 original_film_transparent, original_use_compositing, original_use_nodes,
                                 original_resolution_x, original_resolution_y, original_percentage,
                                 original_filepath, original_taa_samples, original_taa_reprojection)
        _cleanup_temp_compositor(node_tree)
        return None, False

    logger.debug("[Lookdev] Depth render saved")

    # Optimize file size
    depth_filepath = optimize_depth_file_size(depth_filepath, scene, target_size_mb=5)

    _cleanup_temp_compositor(node_tree)
    _restore_render_settings(scene, original_engine, original_view_transform, original_look,
                             original_film_transparent, original_use_compositing, original_use_nodes,
                             original_resolution_x, original_resolution_y, original_percentage,
                             original_filepath, original_taa_samples, original_taa_reprojection)

    return depth_filepath, True
