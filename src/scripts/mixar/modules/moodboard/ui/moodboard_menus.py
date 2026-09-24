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

from ..core.node_templates import template_available

from mixar.modules.common.utils.mixie_space_utils import (
    MIXIE_SPACE_AVAILABLE,
    get_selected_moodboard_items,
)
from mixar.modules.moodboard.core import node_layout

from .moodboard_menu_actions import (
    capability_available as _capability_available,
    connected_action as _connected_action,
    draw_character_sheet_entry as _draw_character_sheet_entry,
    link_drop_anchor as _link_drop_anchor,
    mesh_continuations_for as _mesh_continuations_for,
    mesh_source_id as _mesh_source_id,
)


class MIXIE_MT_moodboard_context_menu(Menu):
    """Right-click context menu for moodboard"""
    bl_label = "Moodboard"
    bl_idname = "MIXIE_MT_moodboard_context_menu"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check selection state
        selected_images, selected_textboxes, selected_frames = (
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
                # A node that has already produced a result is past the point
                # this menu was written for: Edit reopens the tile with its own
                # prompt and Generate, so a second Generate here (and the rename
                # entry, which stays on F2 and the card header) is chrome the
                # card already carries.
                finished = bool(
                    (action_node.preview_image or action_node.preview_object)
                    and action_node.state in {'SUCCESS', 'FAILED', 'CANCELLED'}
                )
                if action_node.state in {'QUEUED', 'RUNNING'}:
                    # Running work offers the one action that applies to it —
                    # "Run Node" here could only report "already running".
                    cancel = layout.operator(
                        "mixie.moodboard_cancel_action_node",
                        text="Cancel Generation",
                        icon='CANCEL',
                    )
                    cancel.node_id = action_node.node_id
                elif finished:
                    # A finished node's way back into editing is the card's
                    # floating Edit toggle. Mirror it here rather than the old
                    # `edit_before_run` path, which reset the node's state to
                    # DRAFT — discarding its real outcome and its error — just
                    # to make the prompt reappear.
                    #
                    # "Cancel Edit", not "Done": finishing an edit is pressing
                    # Generate in the tile. The only thing this can mean while
                    # editing is backing out and keeping the existing result.
                    toggle = layout.operator(
                        "mixie.moodboard_toggle_node_edit",
                        text="Cancel Edit" if action_node.edit_mode
                        else "Edit Node",
                        icon='X' if action_node.edit_mode
                        else 'GREASEPENCIL',
                    )
                    toggle.node_id = action_node.node_id
                else:
                    # Assemble is local: same run operator, its own verb
                    # (matching the card's button).
                    run = layout.operator(
                        "mixie.moodboard_run_action_node",
                        text="Assemble" if action_node.action_type == 'ASSEMBLE' else "Generate",
                        icon='PLAY',
                    )
                    run.node_id = action_node.node_id
                    run.edit_before_run = False
                if not finished:
                    rename = layout.operator(
                        "mixie.moodboard_rename_node",
                        text="Rename Node",
                        icon='FONT_DATA',
                    )
                    rename.node_id = action_node.node_id
                delete = layout.operator(
                    "mixie.moodboard_delete_action_node", text="Delete Node", icon='TRASH'
                )
                delete.node_id = action_node.node_id
                # Act on the whole node SELECTION, not just the right-clicked
                # node, so several nodes duplicate together with the links
                # between them intact. The shortcut is spelled out in the label:
                # Shift+D reaches this through `mixie.moodboard_duplicate`, a
                # different operator, so Blender cannot show it here by itself.
                layout.operator(
                    "mixie.moodboard_duplicate_nodes",
                    text="Duplicate Nodes (Shift D)",
                    icon='DUPLICATE',
                )
                # Copies the whole selection (nodes, links, media) to the
                # clipboard AND the shared copy buffer, so it also pastes in
                # another Mixar instance.
                layout.operator("mixie.moodboard_copy_image", text="Copy", icon='COPYDOWN')
                layout.separator()

                can_continue = action_node.action_type in {
                    'IMAGE_GEN', 'VIDEO_GEN', 'VIDEO_UPSCALE',
                }
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
                    if template_available('CHARACTER_PARTS'):
                        _connected_action(layout, 'CHARACTER_PARTS', "Character Parts",
                                          'OUTLINER_OB_ARMATURE', action_node.node_id)
                    if _capability_available("world_labs"):
                        _connected_action(
                            layout,
                            'WORLD_LABS',
                            "Generate Splat",
                            'WORLD',
                            action_node.node_id,
                        )
                    if template_available('CHARACTER_SHEET_3D'):
                        _draw_character_sheet_entry(layout, action_node.node_id)
                if can_continue and _capability_available("video_gen"):
                    _connected_action(
                        layout,
                        'VIDEO_GEN',
                        "Generate Video",
                        'FILE_MOVIE',
                        action_node.node_id,
                    )
                # Only a node whose OUTPUT is a movie can feed the upscaler.
                if action_node.action_type in {'VIDEO_GEN', 'VIDEO_UPSCALE'} and (
                    _capability_available("video_upscale")
                ):
                    _connected_action(
                        layout, 'VIDEO_UPSCALE', "Upscale Video",
                        'FULLSCREEN_ENTER', action_node.node_id,
                    )
                layout.separator()

        # 3D mesh continuations: available whenever a node holding a 3D mesh is
        # active/selected (a Generate-to-3D result, an imported/pasted mesh, or a
        # mesh produced by an earlier 3D feature — so features chain).
        mesh_source = _mesh_source_id(scene)
        if mesh_source:
            drew_mesh = False
            for action_type, text, icon, _capability in _mesh_continuations_for(scene, mesh_source):
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
            if selected_stills > 0 and template_available('CHARACTER_PARTS'):
                _connected_action(layout, 'CHARACTER_PARTS', "Character Parts", 'OUTLINER_OB_ARMATURE')
            # Click path: the selected stills are the sheet(s) the workflow reads.
            if selected_stills > 0 and template_available('CHARACTER_SHEET_3D'):
                _draw_character_sheet_entry(layout)
            if selected_stills > 0 and _capability_available("world_labs"):
                _connected_action(
                    layout, 'WORLD_LABS', "Generate Splat", 'WORLD'
                )
            if _capability_available("video_gen"):
                _connected_action(
                    layout, 'VIDEO_GEN', "Generate Video", 'FILE_MOVIE'
                )
            if selected_images > selected_stills and _capability_available("video_upscale"):
                _connected_action(
                    layout, 'VIDEO_UPSCALE', "Upscale Video", 'FULLSCREEN_ENTER'
                )
            # Multi Lasso Mask launches the lasso tool on the one selected
            # still; each SAM3-refined loop spawns a connected mask-detail node.
            # Shown whenever exactly one still is selected: the lasso + SAM3
            # refinement (and the mask components it produces) work regardless
            # of the catalog. Only the spawned node's Generate needs a
            # mask-guidance image_gen model, and that already fails closed with
            # a message, so the tool itself is never hidden.
            if selected_stills == 1:
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

        # Frames. A selected frame gets its whole More menu here (the same one
        # its floating button opens, so the two can never drift); otherwise the
        # only frame action that makes sense is making one.
        if selected_frames == 1:
            layout.menu("MIXIE_MT_moodboard_frame", icon='GROUP')
            layout.separator()
        elif selected_frames > 1:
            layout.operator(
                "mixie.moodboard_ungroup", text="Ungroup Frames", icon='UGLYPACKAGE'
            )
            layout.separator()
        else:
            # Always offered, not just with 2+ selected: a frame with its own
            # rect can be created EMPTY and dropped into afterwards, which is
            # most of the reason it is a real object rather than a bounding box.
            layout.operator(
                "mixie.moodboard_create_frame",
                text="Frame Selection" if total_items_selected else "Add Frame",
                icon='GROUP',
            )
            if any(
                getattr(item, "frame_id", "")
                for item in scene.mixie_moodboard_images
                if item.selected
            ):
                layout.operator(
                    "mixie.moodboard_ungroup", text="Ungroup", icon='UGLYPACKAGE'
                )
            layout.separator()

        # Add content — canvas-level actions, shown only when no image is
        # selected. A right-clicked image gets an image-focused menu, not the
        # "add stuff to the canvas" actions.
        if selected_images == 0:
            layout.operator_context = 'INVOKE_DEFAULT'
            layout.operator("mixie.moodboard_add_existing_image", text="Add Existing Media", icon='TRIA_DOWN')
            layout.operator("mixie.moodboard_add_image", text="Open Image or Video", icon='FILE_FOLDER')
            layout.operator("mixie.moodboard_paste_image", text="Paste from Clipboard", icon='PASTEDOWN')
            layout.operator("mixie.moodboard_add_textbox", text="Add Text", icon='FONT_DATA')
            layout.separator()

        # Annotations stay outside that gate: they act on strokes already on the
        # canvas (colour, width, visibility, undo, clear), which is wanted just
        # as much with a reference image selected as on an empty board.
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.menu("MIXIE_MT_canvas_annotations", icon='GREASEPENCIL')
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

        # Transform operations (only enabled when images are selected). Crop is
        # a modal tool, so set the invoke context here regardless of whether the
        # gated "Add content" block above ran.
        layout.operator_context = 'INVOKE_DEFAULT'
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

        row = layout.row()
        row.enabled = total_items_selected > 0
        row.operator("mixie.moodboard_copy_image", text="Copy", icon='COPYDOWN')

        layout.separator()

        # One walk of the board, shared by Arrange and Frame Selected below:
        # `board_items` is the definition of "everything on the canvas that has
        # a position and a size", which is also exactly the set the C++ frame
        # operator unions (media, text boxes, action and asset nodes).
        try:
            board = node_layout.board_items(scene)
        except Exception:
            board = []

        # Arrange acts on the selection, or the whole board when nothing is
        # selected, so it belongs at canvas level rather than on one card. It
        # moves images and text boxes as well as nodes, so gating it on nodes
        # alone hid it from exactly the boards that most need tidying.
        if len(board) >= 2:
            layout.menu("MIXIE_MT_moodboard_arrange", icon='SNAP_GRID')
            layout.separator()

        # Selection — canvas-level, hidden when acting on a selected image.
        if selected_images == 0:
            layout.operator("mixie.moodboard_select_all", text="Select All", icon='CHECKBOX_HLT')
            layout.operator("mixie.moodboard_deselect_all", text="Deselect All", icon='CHECKBOX_DEHLT')

        # Frame Selected belongs with them, but must NOT hide when an image is
        # selected -- that is precisely when it is wanted. Disabled rather than
        # dropped when nothing is selected, so the shortcut beside it is still
        # there to be read and used later.
        #
        # The shortcut is written into the label: the binding lives in the
        # C-registered Mixie space keymap (`space_mixie.cc`, Numpad Period with
        # `selected_only`), and Blender only draws a menu item's shortcut when
        # it can match one whose properties agree -- which it does not do for a
        # property-carrying item in a custom space keymap.
        frame_row = layout.row()
        frame_row.enabled = any(item.selected for item in board)
        frame = frame_row.operator(
            "mixie.moodboard_frame",
            text="Frame Selected (Numpad .)",
            icon='ZOOM_SELECTED',
        )
        frame.selected_only = True
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
        row.enabled = (total_items_selected + selected_frames + selected_links) > 0
        row.operator("mixie.moodboard_delete", text="Delete", icon='TRASH')


# Only include menu if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_context_menu,
) if MIXIE_SPACE_AVAILABLE else ()
