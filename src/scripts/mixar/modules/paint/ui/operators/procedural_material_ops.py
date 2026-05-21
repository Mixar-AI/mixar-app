# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural material application operators for Mixar layers system.

This module provides operators for adding custom procedural materials,
applying materials to existing layers, and clearing materials from layers.

All procedural outputs flow through the full channel pipeline with blend
modes, opacity, and masks. Missing channels are auto-created before the
layer is added.
"""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
from ...core.node.node_utils import get_active_mpaint_node
from ...core.layer.ensure_procedural_channels import ensure_channels_for_procedural
from ...procedural_materials import material_registry
from ..utils.ui_refresh import request_ui_refresh

logger = get_logger(__name__)


class LAYERS_OT_AddCustomProceduralLayer(Operator):
    """Add a custom procedural material layer"""

    bl_idname = "layers.add_custom_procedural_layer"
    bl_label = "Add Procedural Material"
    bl_description = "Add a custom procedural material layer"
    bl_options = {"REGISTER", "UNDO"}

    material_id: StringProperty(
        name="Material ID",
        description="ID of the procedural material to add",
        default=""
    )

    apply_to_existing: BoolProperty(
        name="Apply to Existing Layer",
        description="Apply material to active Fill layer instead of creating new layer",
        default=False
    )

    def execute(self, context):
        """Create a new layer with custom procedural material or apply to existing.

        If apply_to_existing is True and there's an active Fill layer with
        source_type='MATERIAL', updates that layer instead of creating new one.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """

        # Get the material from registry to verify it exists
        material = material_registry.get_material(self.material_id)
        if not material:
            self.report({'ERROR'}, f"Material '{self.material_id}' not found in registry")
            return {'CANCELLED'}

        # Get active mpaint node to verify setup
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar Paint node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Check if we should apply to existing layer
        # Auto-detect: if active layer is Fill with MATERIAL source type, apply to it
        should_apply_to_existing = self.apply_to_existing
        if not should_apply_to_existing and mp.active_layer_index >= 0:
            active_layer = mp.layers[mp.active_layer_index] if mp.active_layer_index < len(mp.layers) else None
            if active_layer and active_layer.type == 'COLOR' and active_layer.source_type == 'MATERIAL':
                should_apply_to_existing = True

        if should_apply_to_existing:
            # Apply to existing layer
            result = bpy.ops.layers.apply_material_to_layer(material_id=self.material_id)
            if result == {'FINISHED'}:
                self.report({'INFO'}, f"Applied material '{material.name}' to existing layer")
                return {'FINISHED'}
            # If it failed or was cancelled, fall through to create new layer

        try:
            # Fetch script synchronously on first use (blocking, ~1-2s).
            # get_node_group_blocking() returns the cached node group immediately
            # on subsequent clicks.
            node_group = material_registry.get_node_group_blocking(self.material_id)
            if not node_group:
                self.report(
                    {'ERROR'},
                    f"Could not load script for '{material.name}' — check your connection"
                )
                return {'CANCELLED'}

            ensure_channels_for_procedural(node.node_tree, mp, node_group)

            # Generate a unique layer name (append suffix if name is taken)
            base_name = material.name
            layer_name = base_name
            existing_names = {lay.name for lay in mp.layers}
            if layer_name in existing_names:
                i = 2
                while f"{base_name} ({i})" in existing_names:
                    i += 1
                layer_name = f"{base_name} ({i})"

            # Create the PROCEDURAL layer — it will get channel entries for
            # all channels, including any we just created above.
            bpy.ops.wm.m_new_layer(
                'EXEC_DEFAULT',
                type='PROCEDURAL',
                procedural_material_id=self.material_id,
                name=layer_name
            )

            self.report({'INFO'}, f"Added procedural material layer: {material.name}")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to create procedural material layer: {e}")
            logger.error("Failed to create procedural material layer: %s", e, exc_info=True)
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_ApplyMaterialToLayer(Operator):
    """Apply procedural material to existing fill layer"""

    bl_idname = "layers.apply_material_to_layer"
    bl_label = "Apply Material to Layer"
    bl_description = "Apply a procedural material to the active fill layer"
    bl_options = {"REGISTER", "UNDO"}

    material_id: StringProperty(
        name="Material ID",
        description="ID of the procedural material to apply",
        default=""
    )

    @classmethod
    def poll(cls, context):
        """Check if there's an active Fill layer that can receive material."""
        node = get_active_mpaint_node()
        if not node:
            return False
        mp = node.node_tree.mp
        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            return False
        layer = mp.layers[mp.active_layer_index]
        # Only works on Fill layers (type='COLOR')
        return layer.type == 'COLOR'

    def execute(self, context):
        """Apply procedural material to the active fill layer.

        Replaces the layer's source node with a ShaderNodeGroup containing
        the procedural material's node tree.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        from ...core.node.get_nodes import get_layer_source
        from ...core.subtree.get_subtree import get_tree
        from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
        from ...core.io.connections.layer_connections import reconnect_layer_nodes
        from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
        from ...core.lib.lib_operations import duplicate_lib_node_tree

        # Get material from registry
        material = material_registry.get_material(self.material_id)
        if not material:
            self.report({'ERROR'}, f"Material '{self.material_id}' not found in registry")
            return {'CANCELLED'}

        # Get node group for material
        node_group = material_registry.get_node_group(self.material_id)
        if not node_group:
            self.report({'ERROR'}, f"Could not load node group for material '{self.material_id}'")
            return {'CANCELLED'}

        # Get active mpaint node
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar Paint node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            self.report({'ERROR'}, "No active layer selected")
            return {'CANCELLED'}

        layer = mp.layers[mp.active_layer_index]

        # Only works on Fill layers
        if layer.type != 'COLOR':
            self.report({'ERROR'}, "This operation only works on Fill layers")
            return {'CANCELLED'}

        try:
            # Auto-create any missing channels for this material's outputs
            ensure_channels_for_procedural(node.node_tree, mp, node_group)

            # Get the layer's node tree
            tree = get_tree(layer)
            if not tree:
                self.report({'ERROR'}, "Could not access layer node tree")
                return {'CANCELLED'}

            # Get current source node
            old_source = get_layer_source(layer, tree)
            old_location = old_source.location.copy() if old_source else (0, 0)

            # Remove old source node
            if old_source:
                logger.debug(f"Removing old source node: {old_source.name}")
                tree.nodes.remove(old_source)

            # Create new ShaderNodeGroup for material
            new_source = tree.nodes.new('ShaderNodeGroup')
            new_source.name = layer.source if layer.source else 'Source'
            new_source.label = 'Source'
            new_source.location = old_location

            # Set the node group
            new_source.node_tree = node_group
            # Duplicate to avoid sharing node tree between layers
            duplicate_lib_node_tree(new_source)

            # Update layer.source to point to the new node
            layer.source = new_source.name

            # Update layer properties
            layer.source_type = 'MATERIAL'
            layer.procedural_material_id = self.material_id

            # Reconnect and rearrange nodes
            check_layer_tree_ios(layer, tree)
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

            logger.info(f"Applied material '{material.name}' to layer '{layer.name}'")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to apply material: {e}")
            logger.error("Failed to apply material: %s", e, exc_info=True)
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_ClearLayerMaterial(Operator):
    """Clear procedural material from fill layer"""

    bl_idname = "layers.clear_layer_material"
    bl_label = "Clear Layer Material"
    bl_description = "Remove procedural material from fill layer and revert to solid color"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Clear procedural material from the active fill layer.

        Changes layer source_type back to SOLID_COLOR and replaces
        the ShaderNodeGroup with a ShaderNodeRGB.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        from ...core.node.get_nodes import get_layer_source, get_tree

        # Get active mpaint node
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar Paint node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            self.report({'ERROR'}, "No active layer selected")
            return {'CANCELLED'}

        layer = mp.layers[mp.active_layer_index]

        # Only works on Fill layers with MATERIAL source
        if layer.type != 'COLOR':
            self.report({'ERROR'}, "This operation only works on Fill layers")
            return {'CANCELLED'}

        if layer.source_type != 'MATERIAL':
            self.report({'INFO'}, "Layer is not using a procedural material")
            return {'FINISHED'}

        try:
            # Get the layer's node tree
            tree = get_tree(layer)
            if not tree:
                self.report({'ERROR'}, "Could not access layer node tree")
                return {'CANCELLED'}

            # Get current source node (should be ShaderNodeGroup)
            source = get_layer_source(layer, tree)
            if not source:
                self.report({'ERROR'}, "Could not find source node")
                return {'CANCELLED'}

            # Store location for new node
            location = source.location.copy() if source else (0, 0)

            # Remove the ShaderNodeGroup
            tree.nodes.remove(source)

            # Create new ShaderNodeRGB
            new_source = tree.nodes.new('ShaderNodeRGB')
            new_source.name = layer.source
            new_source.label = layer.source
            new_source.location = location

            # Set default color (white)
            new_source.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

            # Update layer properties
            layer.source_type = 'SOLID_COLOR'
            layer.procedural_material_id = ''

            self.report({'INFO'}, "Material cleared, reverted to solid color")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear material: {e}")
            logger.error("Failed to clear material: %s", e, exc_info=True)
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_AddCustomProceduralLayer,
    LAYERS_OT_ApplyMaterialToLayer,
    LAYERS_OT_ClearLayerMaterial,
)
