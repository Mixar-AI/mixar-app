# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Context Menus

Right-click context menu for moodboard operations.
"""

import bpy
from bpy.types import Menu

from mixar.modules.common.utils.mixie_space_utils import (
    MIXIE_SPACE_AVAILABLE,
    get_selected_moodboard_items,
)


def _capability_available(capability: str) -> bool:
    """Whether this capability has an enabled model on the moodboard surface.

    The surface filter is not optional: services are tagged ``moodboard`` or
    ``paint``, and a paint-only service (``brush_gen`` under ``image_gen``)
    must never make a canvas action look available.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_models, get_services

        return any(
            get_models(service.get("key") or "")
            for service in get_services(capability, surface="moodboard")
        )
    except Exception:
        return False


def _connected_action(layout, action_type: str, text: str, icon: str, source=""):
    op = layout.operator(
        "mixie.moodboard_create_connected_action", text=text, icon=icon
    )
    op.action_type = action_type
    op.source_node_id = source
    return op


class MIXIE_MT_moodboard_context_menu(Menu):
    """Right-click context menu for moodboard"""
    bl_label = "Moodboard"
    bl_idname = "MIXIE_MT_moodboard_context_menu"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check selection state
        selected_images, selected_textboxes, selected_groups = (
            get_selected_moodboard_items(scene)
        )
        total_items_selected = selected_images + selected_textboxes
        selected_stills = sum(
            1 for item in scene.mixie_moodboard_images
            if item.selected and item.image and item.image.source != 'MOVIE'
        )
        selected_links = sum(
            1 for link in scene.mixie_moodboard_links if link.selected
        )

        if selected_links:
            layout.operator(
                "mixie.moodboard_delete", text="Delete Connection", icon='UNLINKED'
            )
            layout.separator()

        active_graph_node = getattr(scene, "mixie_moodboard_active_node_id", "")
        action_node = None
        if active_graph_node:
            try:
                from mixar.modules.moodboard.core.node_graph import action_node_by_id

                action_node = action_node_by_id(scene, active_graph_node)
            except Exception:
                action_node = None
            if action_node is not None:
                rerun = action_node.state not in {'DRAFT', 'QUEUED', 'RUNNING'}
                run = layout.operator(
                    "mixie.moodboard_run_action_node",
                    text="Edit & Run Again" if rerun else "Run Node",
                    icon='GREASEPENCIL' if rerun else 'PLAY',
                )
                run.node_id = action_node.node_id
                run.edit_before_run = rerun
                delete = layout.operator(
                    "mixie.moodboard_delete_action_node", text="Delete Node", icon='TRASH'
                )
                delete.node_id = action_node.node_id
                layout.separator()

                can_continue = action_node.action_type in {'IMAGE_GEN', 'VIDEO_GEN'}
                if can_continue:
                    layout.label(text="Continue With")
                if action_node.action_type == 'IMAGE_GEN':
                    _connected_action(
                        layout,
                        'IMAGE_GEN',
                        "Generate Image",
                        'IMAGE_DATA',
                        action_node.node_id,
                    )
                    _connected_action(
                        layout,
                        'MODEL_3D',
                        "Generate to 3D",
                        'MESH_DATA',
                        action_node.node_id,
                    )
                if can_continue and _capability_available("video_gen"):
                    _connected_action(
                        layout,
                        'VIDEO_GEN',
                        "Generate Video",
                        'FILE_MOVIE',
                        action_node.node_id,
                    )
                layout.separator()

        if selected_images > 0:
            layout.label(text="Create Connected Node")
            _connected_action(
                layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA'
            )
            row = layout.row()
            row.enabled = selected_stills > 0
            _connected_action(row, 'MODEL_3D', "Generate to 3D", 'MESH_DATA')
            if _capability_available("video_gen"):
                _connected_action(
                    layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE'
                )
            layout.separator()
        elif action_node is None:
            layout.label(text="Create Node")
            _connected_action(
                layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA'
            )
            if _capability_available("video_gen"):
                _connected_action(
                    layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE'
                )
            layout.separator()

        # Check if any selected images belong to a group
        has_grouped_selection = any(
            img.selected and img.group_index >= 0
            for img in scene.mixie_moodboard_images
        )

        # Group operations - show contextually
        if selected_groups > 0 or has_grouped_selection:
            layout.operator("mixie.ungroup", text="Ungroup", icon='UGLYPACKAGE')
            layout.separator()
        elif total_items_selected >= 2:
            layout.operator("mixie.create_group", text="Group", icon='GROUP')
            layout.separator()

        # Add content
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator("mixie.moodboard_add_existing_image", text="Add Existing Media", icon='TRIA_DOWN')
        layout.operator("mixie.moodboard_add_image", text="Open Image or Video", icon='FILE_FOLDER')
        layout.operator("mixie.moodboard_paste_image", text="Paste from Clipboard", icon='PASTEDOWN')
        layout.operator("mixie.moodboard_add_textbox", text="Add Text", icon='FONT_DATA')

        layout.separator()

        # Text box editing (only shown when exactly one text box is selected)
        if selected_textboxes == 1:
            for i, tb in enumerate(scene.mixie_moodboard_textboxes):
                if tb.selected:
                    layout.operator_context = 'INVOKE_DEFAULT'
                    op = layout.operator(
                        "mixie.moodboard_edit_textbox",
                        text="Edit Text Content",
                        icon='GREASEPENCIL',
                    )
                    op.index = i

                    op2 = layout.operator(
                        "mixie.moodboard_update_textbox_properties",
                        text="Edit Text Properties",
                        icon='PROPERTIES',
                    )
                    op2.index = i
                    break
            layout.separator()

        # Transform operations (only enabled when images are selected)
        row = layout.row()
        row.enabled = selected_stills > 0
        row.operator("mixie.moodboard_crop_tool", text="Crop", icon='FULLSCREEN_EXIT')

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.rotate_images", text="Rotate 90°", icon='LOOP_FORWARDS').angle = 90.0

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.flip_horizontal", text="Flip Horizontal", icon='ARROW_LEFTRIGHT')

        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.flip_vertical", text="Flip Vertical", icon='EMPTY_SINGLE_ARROW')

        row = layout.row()
        row.enabled = total_items_selected > 0
        row.operator("mixie.moodboard_duplicate", text="Duplicate", icon='DUPLICATE')

        layout.separator()

        # Selection
        layout.operator("mixie.moodboard_select_all", text="Select All", icon='CHECKBOX_HLT')
        layout.operator("mixie.moodboard_deselect_all", text="Deselect All", icon='CHECKBOX_DEHLT')

        layout.separator()

        # Export (only enabled when images are selected)
        row = layout.row()
        row.enabled = selected_images > 0
        row.operator("mixie.moodboard_export_images", text="Export", icon='EXPORT')

        layout.separator()

        # Delete (only enabled when something is selected)
        row = layout.row()
        row.enabled = (total_items_selected + selected_groups + selected_links) > 0
        row.operator("mixie.moodboard_delete", text="Delete", icon='TRASH')


class MIXIE_MT_moodboard_output_menu(Menu):
    """Compact continuation menu opened from a node's output plus."""

    bl_label = "Create Next Node"
    bl_idname = "MIXIE_MT_moodboard_output_menu"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        try:
            from mixar.modules.moodboard.core.node_graph import node_output_type

            source_id = str(scene.mixie_moodboard_output_source_id or "")
            source_type = node_output_type(scene, source_id)
        except Exception:
            source_id = ""
            source_type = ""

        added = False
        if source_type == 'IMAGE' and _capability_available("image_gen"):
            _connected_action(
                layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA', source_id
            )
            added = True
        if source_type == 'IMAGE' and _capability_available("model_gen"):
            _connected_action(
                layout, 'MODEL_3D', "Generate 3D", 'MESH_DATA', source_id
            )
            added = True
        if source_type in {'IMAGE', 'VIDEO'} and _capability_available("video_gen"):
            _connected_action(
                layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE', source_id
            )
            added = True
        if not added:
            layout.label(text="No compatible continuation", icon='INFO')


# Only include menu if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_context_menu,
    MIXIE_MT_moodboard_output_menu,
) if MIXIE_SPACE_AVAILABLE else ()
