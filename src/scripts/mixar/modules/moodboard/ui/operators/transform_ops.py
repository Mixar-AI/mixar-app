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

from ...core.image_lifecycle import release_all_moodboard_images


def get_selected_group_indices(scene):
    """Get indices of all selected groups."""
    selected_group_indices = set()
    for i, group in enumerate(scene.mixie_moodboard_groups):
        if group.selected:
            selected_group_indices.add(i)
    return selected_group_indices


def get_group_indices_from_selected_items(scene):
    """Get group indices of selected images (for group cohesion)."""
    group_indices = set()
    for img in scene.mixie_moodboard_images:
        if img.selected and img.group_index >= 0:
            group_indices.add(img.group_index)
    return group_indices


def get_all_items_to_transform(scene):
    """
    Get all items that should be transformed based on selection.

    Returns tuple of (image_indices, textbox_indices) that should be transformed.
    This includes:
    - Directly selected images and textboxes
    - Images from selected groups
    - All images in a group if any image in that group is selected (group cohesion)
    """
    image_indices = set()
    textbox_indices = set()

    # Get selected group indices
    selected_group_indices = get_selected_group_indices(scene)

    # Get group indices from selected images (group cohesion)
    cohesion_group_indices = get_group_indices_from_selected_items(scene)

    # Combine all group indices that need to be transformed
    all_group_indices = selected_group_indices | cohesion_group_indices

    # Collect images
    for i, img in enumerate(scene.mixie_moodboard_images):
        if img.selected:
            image_indices.add(i)
        elif img.group_index in all_group_indices:
            # Image belongs to a group being transformed
            image_indices.add(i)

    # Collect textboxes (only directly selected for now, as textboxes don't have groups)
    for i, tb in enumerate(scene.mixie_moodboard_textboxes):
        if tb.selected:
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
    """Clear all images, text boxes and groups from the moodboard"""

    bl_idname = "mixie.clear_moodboard"
    bl_label = "Clear Moodboard"
    bl_description = "Remove all images, text boxes and groups from the moodboard"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        image_count = len(scene.mixie_moodboard_images)
        textbox_count = len(scene.mixie_moodboard_textboxes)
        group_count = len(scene.mixie_moodboard_groups)

        if image_count == 0 and textbox_count == 0 and group_count == 0:
            self.report({'INFO'}, "Moodboard is already empty")
            return {'CANCELLED'}

        release_all_moodboard_images(scene)
        scene.mixie_moodboard_images.clear()
        scene.mixie_moodboard_textboxes.clear()
        scene.mixie_moodboard_groups.clear()

        tag_mixie_redraw(context)

        parts = []
        if image_count > 0:
            parts.append(f"{image_count} image(s)")
        if textbox_count > 0:
            parts.append(f"{textbox_count} text box(es)")
        if group_count > 0:
            parts.append(f"{group_count} group(s)")
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

        if not image_indices and not textbox_indices:
            self.report({'WARNING'}, "No items selected to duplicate")
            return {'CANCELLED'}

        # Deselect all original items and groups
        for img in scene.mixie_moodboard_images:
            img.selected = False
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for group in scene.mixie_moodboard_groups:
            group.selected = False

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

        self.report({'INFO'}, f"Duplicated {duplicated_count} item(s) - move to position")

        # Invoke grab mode for the duplicated items
        bpy.ops.mixie.moodboard_grab('INVOKE_DEFAULT')

        return {'FINISHED'}


class MIXIE_OT_moodboard_select_all(Operator):
    """Select all moodboard images and text boxes"""

    bl_idname = "mixie.moodboard_select_all"
    bl_label = "Select All"
    bl_description = "Select all images and text boxes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        count = 0
        for img in scene.mixie_moodboard_images:
            if not img.selected:
                img.selected = True
                count += 1
        for tb in scene.mixie_moodboard_textboxes:
            if not tb.selected:
                tb.selected = True
                count += 1
        tag_mixie_redraw(context)
        self.report({'INFO'}, f"Selected {count} item(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_deselect_all(Operator):
    """Deselect all moodboard images, text boxes and groups"""

    bl_idname = "mixie.moodboard_deselect_all"
    bl_label = "Deselect All"
    bl_description = "Deselect all images, text boxes and groups"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        for img in scene.mixie_moodboard_images:
            img.selected = False
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for grp in scene.mixie_moodboard_groups:
            grp.selected = False
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
