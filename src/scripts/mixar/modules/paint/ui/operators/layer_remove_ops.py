# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer removal operator for Mixar layers system"""

import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.io.utils.bsdf_connections import commit_mp_material
from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ..utils.ui_refresh import request_ui_refresh


class LAYERS_OT_RemoveActiveLayer(Operator):
    """Remove the active layer"""

    bl_idname = "layers.remove_active_layer"
    bl_label = "Remove Active Layer"
    bl_description = "Remove the active layer"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        description="Index of the layer to remove. If -1, uses active layer",
        default=-1
    )

    # Confirmation properties
    confirm: BoolProperty(
        name="Confirm",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        """Show confirmation dialog if layer has children.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from confirmation dialog or execute().
        """
        # Get backend layer to check for children
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            return {'CANCELLED'}

        mat = obj.active_material
        # Find Mixar group node
        node = None
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                node = n
                break

        if not node:
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_index if self.layer_index >= 0 else mp.active_layer_index

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Check if layer has children (masks)
        has_children = len(layer.masks) > 0

        if has_children and not self.confirm:
            # Show confirmation dialog
            return context.window_manager.invoke_confirm(self, event)
        else:
            # No children or already confirmed, execute directly
            return self.execute(context)

    def draw(self, context):
        """Draw confirmation dialog showing layer and child counts.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # Get layer info for dialog
        obj = context.active_object
        if obj and obj.active_material and obj.active_material.use_nodes:
            mat = obj.active_material
            node = None
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                    node = n
                    break

            if node:
                tree = node.node_tree
                mp = tree.mp
                # Use provided layer index, or fall back to active layer
                layer_idx = self.layer_index if self.layer_index >= 0 else mp.active_layer_index
                if layer_idx >= 0 and layer_idx < len(mp.layers):
                    layer = mp.layers[layer_idx]

                    # Question text
                    question_row = main_col.row(align=True)
                    question_row.scale_y = 1.2
                    question_row.label(text=f"Remove layer '{layer.name}'?", icon='QUESTION')

                    main_col.separator(factor=0.8)

                    if len(layer.masks) > 0:
                        info_row = main_col.row(align=True)
                        info_row.label(text="This will also remove:", icon='INFO')

                        main_col.separator(factor=0.4)

                        box = main_col.box()
                        box_col = box.column(align=True)
                        box_col.label(text=f"* {len(layer.masks)} mask(s)")

                        main_col.separator(factor=0.4)

    def execute(self, context):
        """Remove the active layer and its children.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Delayed import to avoid circular dependency
        from ..layer.helpers.layer_operation_helpers import remove_layer

        # Get backend layer
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            return {'CANCELLED'}

        mat = obj.active_material
        # Find Mixar group node
        node = None
        for n in mat.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
                node = n
                break

        if not node:
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_index if self.layer_index >= 0 else mp.active_layer_index

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            return {'CANCELLED'}

        # Use backend remove_layer function to properly clean up
        mp.halt_update = True
        try:
            remove_layer(mp, layer_idx, remove_on_disk=False)

            # Adjust active index if the removed layer was active or after active
            # This preserves selection unless the selected layer was removed
            if len(mp.layers) > 0:
                if layer_idx == mp.active_layer_index:
                    # Removed layer was active, select nearest
                    if mp.active_layer_index >= len(mp.layers):
                        mp.active_layer_index = len(mp.layers) - 1
                elif layer_idx < mp.active_layer_index:
                    # Removed layer was before active, shift active index down
                    mp.active_layer_index -= 1
        finally:
            mp.halt_update = False

        # If there are no layers left, remove the Mixar/Mixar Paint group node as well
        # This mirrors the behavior of the dedicated remove-node operator
        if len(mp.layers) == 0:
            try:
                bpy.ops.wm.m_remove_mp_node()
            except Exception:
                # Fail silently if the operator cannot run for some reason
                pass
        else:
            # CRITICAL: Reconnect and rearrange nodes after layer removal (Mixar Paint pattern)
            # This ensures the previous layer's output connects properly to the clamp node
            check_start_end_root_ch_nodes(tree)
            reconnect_mp_nodes(tree)
            rearrange_mp_nodes(tree)
            # Flush the depsgraph so a scripted EXEC_DEFAULT removal (agent path, no
            # UI event loop) re-evaluates and renders instead of serving a stale
            # shader. relink=False: the group already drives the BSDF here, so the
            # (re)build paths own the group->BSDF relink (avoids clobbering a
            # deliberately rewired BSDF, e.g. a baked/preview material).
            commit_mp_material(node, mat, context, relink=False)

        # Request UI refresh after layer removal
        request_ui_refresh()

        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_RemoveActiveLayer,
)
