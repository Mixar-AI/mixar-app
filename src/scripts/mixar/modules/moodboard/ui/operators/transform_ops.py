# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Transform Operators

Operators for transforming and managing moodboard images.
"""

import bpy
from bpy.types import Operator
from bpy.props import FloatProperty

from ...core.canvas_context import redraw_moodboard_canvases
from ...core.image_lifecycle import release_all_moodboard_images
from ...core.moodboard_utils import stamp_moodboard_item_added


def get_selected_frame_ids(scene):
    """Ids of every selected frame."""
    return {
        frame.frame_id
        for frame in getattr(scene, 'mixie_moodboard_frames', ())
        if frame.selected and frame.frame_id
    }


def get_all_items_to_transform(scene):
    """
    Get all items that should be transformed based on selection.

    Returns tuple of (image_indices, textbox_indices) that should be transformed.
    This includes:
    - Directly selected images and textboxes
    - Every member of a SELECTED frame

    Deliberately NOT the reverse: selecting one picture inside a frame does not
    drag its neighbours along. That "group cohesion" rule is exactly the
    inverted selection model the frame rewrite removed -- clicking a member
    selects the member, and the frame is selected by its own border.
    """
    image_indices = set()
    textbox_indices = set()

    selected_frame_ids = get_selected_frame_ids(scene)

    for i, img in enumerate(scene.mixie_moodboard_images):
        if img.selected or (
            selected_frame_ids and getattr(img, 'frame_id', '') in selected_frame_ids
        ):
            image_indices.add(i)

    for i, tb in enumerate(scene.mixie_moodboard_textboxes):
        if tb.selected or (
            selected_frame_ids and getattr(tb, 'frame_id', '') in selected_frame_ids
        ):
            textbox_indices.add(i)

    return image_indices, textbox_indices


def calculate_selection_pivot(scene):
    """
    Calculate the center point of all items to be transformed.

    Shared utility for rotate and scale operators.
    """
    positions = []

    # Get all items to transform (including groups)
    image_indices, textbox_indices = get_all_items_to_transform(scene)

    for i in image_indices:
        if i < len(scene.mixie_moodboard_images):
            img = scene.mixie_moodboard_images[i]
            positions.append((img.position_x, img.position_y))

    for i in textbox_indices:
        if i < len(scene.mixie_moodboard_textboxes):
            tb = scene.mixie_moodboard_textboxes[i]
            positions.append((tb.position_x, tb.position_y))

    if not positions:
        return 0.0, 0.0

    avg_x = sum(p[0] for p in positions) / len(positions)
    avg_y = sum(p[1] for p in positions) / len(positions)
    return avg_x, avg_y


def tag_mixie_redraw(context):
    """Trigger redraw of MIXIE area. Uses cached area if available."""
    # Try context.area first (most efficient in modal context)
    if context.area and context.area.type == 'MIXIE':
        context.area.tag_redraw()
        return

    # Fallback to searching areas
    for area in context.screen.areas:
        if area.type == 'MIXIE':
            area.tag_redraw()
            return


class MIXIE_OT_flip_horizontal(Operator):
    """Flip selected moodboard images horizontally"""

    bl_idname = "mixie.flip_horizontal"
    bl_label = "Flip Horizontal"
    bl_description = "Flip selected moodboard images horizontally"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_images = [img for img in scene.mixie_moodboard_images if img.selected]

        if not selected_images:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}

        for img in selected_images:
            img.flip_horizontal = not img.flip_horizontal

        tag_mixie_redraw(context)

        count = len(selected_images)
        self.report({'INFO'}, f"Flipped {count} image(s) horizontally")
        return {'FINISHED'}


class MIXIE_OT_flip_vertical(Operator):
    """Flip selected moodboard images vertically"""

    bl_idname = "mixie.flip_vertical"
    bl_label = "Flip Vertical"
    bl_description = "Flip selected moodboard images vertically"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_images = [img for img in scene.mixie_moodboard_images if img.selected]

        if not selected_images:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}

        for img in selected_images:
            img.flip_vertical = not img.flip_vertical

        tag_mixie_redraw(context)

        count = len(selected_images)
        self.report({'INFO'}, f"Flipped {count} image(s) vertically")
        return {'FINISHED'}


class MIXIE_OT_rotate_images(Operator):
    """Rotate selected moodboard images by specified angle"""

    bl_idname = "mixie.rotate_images"
    bl_label = "Rotate 90°"
    bl_description = "Rotate selected moodboard images 90° clockwise (R)"
    bl_options = {'REGISTER', 'UNDO'}

    angle: FloatProperty(
        name="Angle",
        description="Rotation angle in degrees",
        default=90.0,
        min=-360.0,
        max=360.0
    )

    def execute(self, context):
        scene = context.scene
        selected_images = [img for img in scene.mixie_moodboard_images if img.selected]

        if not selected_images:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}

        for img in selected_images:
            img.rotation = (img.rotation + self.angle) % 360.0

        tag_mixie_redraw(context)

        count = len(selected_images)
        self.report({'INFO'}, f"Rotated {count} image(s) by {self.angle} degrees")
        return {'FINISHED'}


class MIXIE_OT_clear_moodboard(Operator):
    """Clear all content, including canvas annotations, from the moodboard"""

    bl_idname = "mixie.clear_moodboard"
    bl_label = "Clear Moodboard"
    bl_description = ("Remove all images, text boxes, frames, nodes, connections "
                      "and annotations")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        image_count = len(scene.mixie_moodboard_images)
        textbox_count = len(scene.mixie_moodboard_textboxes)
        frames = getattr(scene, 'mixie_moodboard_frames', None)
        frame_count = len(frames) if frames is not None else 0
        node_count = (
            len(scene.mixie_moodboard_action_nodes)
            + len(scene.mixie_moodboard_asset_nodes)
        )
        link_count = len(scene.mixie_moodboard_links)
        annotation_count = len(scene.mixie_moodboard_annotations)

        if not any((image_count, textbox_count, frame_count, node_count, link_count,
                    annotation_count)):
            self.report({'INFO'}, "Moodboard is already empty")
            return {'CANCELLED'}

        release_all_moodboard_images(scene)
        scene.mixie_moodboard_images.clear()
        scene.mixie_moodboard_textboxes.clear()
        scene.mixie_moodboard_groups.clear()
        if frames is not None:
            frames.clear()
        scene.mixie_moodboard_action_nodes.clear()
        scene.mixie_moodboard_asset_nodes.clear()
        scene.mixie_moodboard_links.clear()
        scene.mixie_moodboard_annotations.clear()
        scene.mixie_moodboard_active_node_id = ""

        redraw_moodboard_canvases()

        parts = []
        if image_count > 0:
            parts.append(f"{image_count} image(s)")
        if textbox_count > 0:
            parts.append(f"{textbox_count} text box(es)")
        if frame_count > 0:
            parts.append(f"{frame_count} frame(s)")
        if node_count > 0:
            parts.append(f"{node_count} node(s)")
        if link_count > 0:
            parts.append(f"{link_count} connection(s)")
        if annotation_count > 0:
            parts.append(f"{annotation_count} annotation stroke(s)")
        self.report({'INFO'}, f"Cleared {', '.join(parts)}")
        return {'FINISHED'}


class MIXIE_OT_moodboard_duplicate(Operator):
    """Duplicate selected moodboard images and text boxes and enter grab mode"""

    bl_idname = "mixie.moodboard_duplicate"
    bl_label = "Duplicate"
    bl_description = "Duplicate selected images and text boxes (Shift+D)"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        scene = context.scene
        duplicated_count = 0

        # Get all items to duplicate (including from groups)
        image_indices, textbox_indices = get_all_items_to_transform(scene)

        # Inference nodes duplicate through their own path: they carry links,
        # sockets and catalog parameters, and they are placed at a fixed offset
        # rather than handed to grab mode (which moves images and text boxes
        # only). Shift+D therefore acts on whatever is actually selected.
        node_count = 0
        try:
            from mixar.modules.moodboard.core import node_duplicate

            node_count = len(node_duplicate.duplicate_selected_nodes(scene))
        except Exception:
            node_count = 0

        if not image_indices and not textbox_indices:
            if node_count:
                tag_mixie_redraw(context)
                self.report(
                    {'INFO'}, f"Duplicated {node_count} node(s) - move to position"
                )
                # Same hand-off as the image path below: the copies land on the
                # originals and grab mode places them.
                bpy.ops.mixie.moodboard_grab('INVOKE_DEFAULT')
                return {'FINISHED'}
            self.report({'WARNING'}, "No items selected to duplicate")
            return {'CANCELLED'}

        # Deselect all original items and frames. The frame matters as much
        # as the members: `get_all_items_to_transform` expands a still-selected
        # frame back into every ORIGINAL member, so leaving it set makes the
        # grab that follows drag the sources along with the copies.
        for img in scene.mixie_moodboard_images:
            img.selected = False
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for frame in getattr(scene, 'mixie_moodboard_frames', ()):
            frame.selected = False

        # Duplicate images (no offset - grab mode will handle positioning)
        for i in image_indices:
            if i >= len(scene.mixie_moodboard_images):
                continue
            orig_img = scene.mixie_moodboard_images[i]
            new_img = scene.mixie_moodboard_images.add()
            new_img.image = orig_img.image
            new_img.position_x = orig_img.position_x
            new_img.position_y = orig_img.position_y
            new_img.scale = orig_img.scale
            new_img.rotation = orig_img.rotation
            new_img.flip_horizontal = orig_img.flip_horizontal
            new_img.flip_vertical = orig_img.flip_vertical
            new_img.z_order = orig_img.z_order + 1
            new_img.generation_prompt = orig_img.generation_prompt
            # Preserve what a generated detail represents, while leaving its
            # moodboard_item_id empty so the duplicate receives a fresh UUID
            # if it later becomes a provenance source itself.
            new_img.component_role = orig_img.component_role
            new_img.component_source_item_id = orig_img.component_source_item_id
            new_img.component_source_segment_id = (
                orig_img.component_source_segment_id
            )
            new_img.component_name = orig_img.component_name
            new_img.show_annotations = orig_img.show_annotations
            for original_stroke in orig_img.annotations:
                copied_stroke = new_img.annotations.add()
                copied_stroke.color = original_stroke.color[:]
                copied_stroke.width = original_stroke.width
                for original_point in original_stroke.points:
                    copied_point = copied_stroke.points.add()
                    copied_point.x = original_point.x
                    copied_point.y = original_point.y
            new_img.group_index = -1  # Don't copy group membership
            new_img.selected = True  # Select the duplicate
            # A duplicate is a NEW board entry, so it is stamped now rather
            # than inheriting the original's age — otherwise it sorts as if it
            # had always been there in every recency-ordered listing.
            stamp_moodboard_item_added(new_img)
            duplicated_count += 1

        # Duplicate text boxes (no offset - grab mode will handle positioning)
        for i in textbox_indices:
            if i >= len(scene.mixie_moodboard_textboxes):
                continue
            orig_tb = scene.mixie_moodboard_textboxes[i]
            new_tb = scene.mixie_moodboard_textboxes.add()
            new_tb.text = orig_tb.text
            new_tb.position_x = orig_tb.position_x
            new_tb.position_y = orig_tb.position_y
            new_tb.font_size = orig_tb.font_size
            new_tb.text_color = orig_tb.text_color[:]
            new_tb.background_color = orig_tb.background_color[:]
            new_tb.width = orig_tb.width
            new_tb.height = orig_tb.height
            new_tb.rotation = orig_tb.rotation
            new_tb.z_order = orig_tb.z_order + 1
            new_tb.bold = orig_tb.bold
            new_tb.italic = orig_tb.italic
            new_tb.align = orig_tb.align
            new_tb.selected = True  # Select the duplicate
            duplicated_count += 1

        tag_mixie_redraw(context)

        duplicated_count += node_count
        self.report({'INFO'}, f"Duplicated {duplicated_count} item(s) - move to position")

        # Invoke grab mode for the duplicated items
        bpy.ops.mixie.moodboard_grab('INVOKE_DEFAULT')

        return {'FINISHED'}


class MIXIE_OT_moodboard_select_all(Operator):
    """Select all moodboard media, text boxes, frames, and graph nodes."""

    bl_idname = "mixie.moodboard_select_all"
    bl_label = "Select All"
    bl_description = "Select all images, text boxes, frames and graph nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        count = 0
        for img in scene.mixie_moodboard_images:
            # Node-owned previews are never directly selected — the owning
            # action/asset card is the selection target (same as box select).
            if getattr(img, "embedded_node_id", ""):
                continue
            if not img.selected:
                img.selected = True
                count += 1
        for tb in scene.mixie_moodboard_textboxes:
            if not tb.selected:
                tb.selected = True
                count += 1
        for frame in getattr(scene, 'mixie_moodboard_frames', ()):
            if not frame.selected:
                frame.selected = True
                count += 1
        # Nodes too. Deselect All has always cleared them, so leaving them out
        # here meant Select All followed by Delete silently spared every node.
        for collection in (scene.mixie_moodboard_action_nodes,
                           scene.mixie_moodboard_asset_nodes):
            for node in collection:
                if not node.selected:
                    node.selected = True
                    count += 1
        # Multi-select has no single active graph node (same as box select), so
        # no card claims the inspector.
        scene.mixie_moodboard_active_node_id = ""
        tag_mixie_redraw(context)
        self.report({'INFO'}, f"Selected {count} item(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_deselect_all(Operator):
    """Deselect all moodboard content, graph nodes, and connections."""

    bl_idname = "mixie.moodboard_deselect_all"
    bl_label = "Deselect All"
    bl_description = "Deselect all images, text boxes and frames"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        for img in scene.mixie_moodboard_images:
            img.selected = False
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for frame in getattr(scene, 'mixie_moodboard_frames', ()):
            frame.selected = False
        for node in scene.mixie_moodboard_action_nodes:
            node.selected = False
        for node in scene.mixie_moodboard_asset_nodes:
            node.selected = False
        for link in scene.mixie_moodboard_links:
            link.selected = False
        scene.mixie_moodboard_active_node_id = ""
        tag_mixie_redraw(context)
        self.report({'INFO'}, "Deselected all")
        return {'FINISHED'}


classes = (
    MIXIE_OT_flip_horizontal,
    MIXIE_OT_flip_vertical,
    MIXIE_OT_rotate_images,
    MIXIE_OT_clear_moodboard,
    MIXIE_OT_moodboard_duplicate,
    MIXIE_OT_moodboard_select_all,
    MIXIE_OT_moodboard_deselect_all,
)
