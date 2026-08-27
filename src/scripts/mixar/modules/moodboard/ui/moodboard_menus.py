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


def _mask_detail_available() -> bool:
    """Whether an image_gen model can detail a cutout/mask pair.

    Gates the "Multi Lasso Mask" action: without a mask-guidance model the
    spawned node's Generate would fail closed, so the action stays hidden.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_models, is_loaded
        from mixar.modules.moodboard.core.character_components import (
            eligible_component_model_slugs,
        )

        return is_loaded() and bool(
            eligible_component_model_slugs(get_models("image_gen"))
        )
    except Exception:
        return False


_MESH_CONTINUATIONS = (
    ('PBR_GEN', "PBR Generation", 'TEXTURE', "pbr_generation"),
    ('RETOPOLOGY', "Retopology", 'MOD_REMESH', "retopology"),
    ('MESH_SEGMENT', "Mesh Segmentation", 'MOD_EXPLODE', "mesh_segmentation"),
    ('AUTO_RIG', "Auto Rig", 'ARMATURE_DATA', "animate"),
)


def _mesh_source_id(scene) -> str:
    """Node id of the active/selected node that currently holds a 3D mesh."""
    try:
        from mixar.modules.moodboard.core.node_graph import node_holds_mesh
    except Exception:
        return ""
    active = str(getattr(scene, "mixie_moodboard_active_node_id", "") or "")
    if active and node_holds_mesh(scene, active):
        return active
    for asset in getattr(scene, "mixie_moodboard_asset_nodes", ()):
        if asset.selected and node_holds_mesh(scene, asset.node_id):
            return asset.node_id
    for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
        if node.selected and node_holds_mesh(scene, node.node_id):
            return node.node_id
    return ""


def _connected_action(
    layout, action_type: str, text: str, icon: str, source="", drop=None
):
    op = layout.operator(
        "mixie.moodboard_create_connected_action", text=text, icon=icon
    )
    op.action_type = action_type
    op.source_node_id = source
    if drop is not None:
        op.use_drop_position = True
        op.drop_x, op.drop_y = drop
    return op


def _link_drop_anchor(scene):
    """Canvas point a dragged noodle was released at, or None.

    Read-only: this runs from a menu draw, so it must never write scene data.
    The C++ graph modal sets the flag just before opening this menu and clears
    it at every other entry point, so a stale anchor cannot leak into a node
    created from the output handle or the right-click menu.
    """
    if not getattr(scene, "mixie_moodboard_link_drop_active", False):
        return None
    return (
        float(getattr(scene, "mixie_moodboard_link_drop_x", 0.0)),
        float(getattr(scene, "mixie_moodboard_link_drop_y", 0.0)),
    )


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
        try:
            from mixar.modules.moodboard.core.media_utils import (
                selected_exportable_media,
            )

            exportable_media = selected_exportable_media(scene)
        except Exception:
            exportable_media = []

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

        # 3D mesh continuations: available whenever a node holding a 3D mesh is
        # active/selected (a Generate-to-3D result, an imported/pasted mesh, or a
        # mesh produced by an earlier 3D feature — so features chain).
        mesh_source = _mesh_source_id(scene)
        if mesh_source:
            drew_mesh = False
            for action_type, text, icon, capability in _MESH_CONTINUATIONS:
                if _capability_available(capability):
                    if not drew_mesh:
                        layout.label(text="Continue in 3D")
                        drew_mesh = True
                    _connected_action(layout, action_type, text, icon, mesh_source)
            if drew_mesh:
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
            # Multi Lasso Mask launches the lasso tool on the one selected still;
            # each SAM3-refined loop spawns a connected mask-detail node.
            if selected_stills == 1 and _mask_detail_available():
                mask_row = layout.row()
                mask_row.operator_context = 'INVOKE_DEFAULT'
                mask_op = mask_row.operator(
                    "mixie.moodboard_lasso_tool",
                    text="Multi Lasso Mask",
                    icon='MOD_MASK',
                )
                mask_op.create_nodes = True
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

        # Export. Gated on the same set the operator exports, which includes a
        # selected node's generated result — that media is never `selected`
        # itself, so gating on selected_images left the row greyed out with no
        # other way to get a generated video off the canvas.
        row = layout.row()
        row.enabled = bool(exportable_media)
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
        drop = _link_drop_anchor(scene)

        added = False
        if source_type == 'IMAGE' and _capability_available("image_gen"):
            _connected_action(
                layout, 'IMAGE_GEN', "Generate Image", 'IMAGE_DATA', source_id, drop
            )
            added = True
        if source_type == 'IMAGE' and _capability_available("model_gen"):
            _connected_action(
                layout, 'MODEL_3D', "Generate 3D", 'MESH_DATA', source_id, drop
            )
            added = True
        if source_type in {'IMAGE', 'VIDEO'} and _capability_available("video_gen"):
            _connected_action(
                layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE', source_id, drop
            )
            added = True
        # A 3D mesh output continues into the mesh -> mesh features, matching the
        # right-click "Continue in 3D" section.
        if source_type == 'MESH':
            drew_mesh = False
            for action_type, text, icon, capability in _MESH_CONTINUATIONS:
                if _capability_available(capability):
                    if not drew_mesh:
                        layout.label(text="Continue in 3D")
                        drew_mesh = True
                    _connected_action(layout, action_type, text, icon, source_id, drop)
                    added = True
        if not added:
            layout.label(text="No compatible continuation", icon='INFO')


# Only include menu if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_context_menu,
    MIXIE_MT_moodboard_output_menu,
) if MIXIE_SPACE_AVAILABLE else ()
