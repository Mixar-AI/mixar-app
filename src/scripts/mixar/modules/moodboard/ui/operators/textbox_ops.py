# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Text Box Operators

Operators for managing text boxes in the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty

from ...core.moodboard_utils import get_moodboard_viewport_center
from ...core.image_lifecycle import release_moodboard_image_entry
from ....common.utils.platform_utils import format_shortcut


class MIXIE_OT_moodboard_add_textbox(Operator):
    """Add a text box to the moodboard"""

    bl_idname = "mixie.moodboard_add_textbox"
    bl_label = "Add Text"
    bl_description = f"Add a text box to the moodboard ({format_shortcut('T')})"
    bl_options = {'REGISTER', 'UNDO'}

    text: StringProperty(
        name="",
        description="Content of the text box",
        default="",
        options={'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        # If no text provided, open dialog
        if not self.text:
            return context.window_manager.invoke_props_dialog(self, width=400)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.activate_init = True
        row.prop(self, "text", text="")

    def execute(self, context):
        scene = context.scene

        if not self.text.strip():
            self.report({'WARNING'}, "Please enter some text")
            return {'CANCELLED'}

        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        item = scene.mixie_moodboard_textboxes.add()
        item.text = self.text
        item.position_x = viewport_cx
        item.position_y = viewport_cy
        item.width = 400.0
        item.height = 100.0
        item.font_size = 48
        item.z_order = len(scene.mixie_moodboard_textboxes) + len(scene.mixie_moodboard_images)

        # Trigger immediate UI redraw
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        self.report({'INFO'}, "Added text box to moodboard")
        return {'FINISHED'}


class MIXIE_OT_moodboard_edit_textbox(Operator):
    """Edit text box content"""

    bl_idname = "mixie.moodboard_edit_textbox"
    bl_label = "Edit Text Box"
    bl_description = "Edit the content of a text box"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of the text box to edit",
        default=-1
    )

    text: StringProperty(
        name="Text",
        description="New text content",
        default="",
        maxlen=1024
    )

    def invoke(self, context, event):
        scene = context.scene

        if self.index == -1:
            for i, textbox in enumerate(scene.mixie_moodboard_textboxes):
                if textbox.selected:
                    self.index = i
                    break

        if self.index == -1 or self.index >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "No text box selected")
            return {'CANCELLED'}

        self.text = scene.mixie_moodboard_textboxes[self.index].text
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scene = context.scene

        if self.index == -1 or self.index >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "Invalid text box index")
            return {'CANCELLED'}

        scene.mixie_moodboard_textboxes[self.index].text = self.text
        self.report({'INFO'}, "Text box updated")
        return {'FINISHED'}


class MIXIE_OT_moodboard_delete(Operator):
    """Delete selected moodboard elements (images, text boxes and groups)"""

    bl_idname = "mixie.moodboard_delete"
    bl_label = "Delete Selected"
    bl_description = "Remove selected images, text boxes and groups from the moodboard"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        moodboard_images = scene.mixie_moodboard_images
        moodboard_groups = scene.mixie_moodboard_groups

        deleted_images = 0
        deleted_textboxes = 0
        deleted_groups = 0

        # First, delete selected groups (in reverse order to maintain indices)
        groups_to_remove = []
        for i in range(len(moodboard_groups) - 1, -1, -1):
            if moodboard_groups[i].selected:
                groups_to_remove.append(i)

        for group_idx in groups_to_remove:
            # Reset group_index for images in this group
            # Also shift indices for images in higher groups
            for img in moodboard_images:
                if img.group_index == group_idx:
                    img.group_index = -1
                elif img.group_index > group_idx:
                    img.group_index -= 1

            moodboard_groups.remove(group_idx)
            deleted_groups += 1

        # Delete selected images (in reverse order to maintain indices)
        indices_to_remove_img = []
        for i in range(len(moodboard_images) - 1, -1, -1):
            if moodboard_images[i].selected:
                indices_to_remove_img.append(i)

        for idx in indices_to_remove_img:
            release_moodboard_image_entry(moodboard_images[idx])
            moodboard_images.remove(idx)
            deleted_images += 1

        # Delete selected text boxes
        textboxes = scene.mixie_moodboard_textboxes
        indices_to_remove_text = []
        for i in range(len(textboxes) - 1, -1, -1):
            if textboxes[i].selected:
                indices_to_remove_text.append(i)

        for idx in indices_to_remove_text:
            textboxes.remove(idx)
            deleted_textboxes += 1

        if deleted_images == 0 and deleted_textboxes == 0 and deleted_groups == 0:
            self.report({'WARNING'}, "No elements selected")
            return {'CANCELLED'}

        # Trigger immediate redraw
        if context.area:
            context.area.tag_redraw()
        # Force region redraw
        if context.region:
            context.region.tag_redraw()

        # Build report message
        parts = []
        if deleted_images > 0:
            parts.append(f"{deleted_images} image(s)")
        if deleted_textboxes > 0:
            parts.append(f"{deleted_textboxes} text box(es)")
        if deleted_groups > 0:
            parts.append(f"{deleted_groups} group(s)")
        self.report({'INFO'}, f"Deleted {', '.join(parts)}")
        return {'FINISHED'}


class MIXIE_OT_moodboard_update_textbox_properties(Operator):
    """Update text box formatting properties (font size, colors, alignment, etc.)"""

    bl_idname = "mixie.moodboard_update_textbox_properties"
    bl_label = "Text Properties"
    bl_description = "Update formatting properties of the selected text box"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of the text box to update",
        default=-1,
        options={'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        scene = context.scene

        # Resolve index from selection if not provided
        if self.index == -1:
            for i, textbox in enumerate(scene.mixie_moodboard_textboxes):
                if textbox.selected:
                    self.index = i
                    break

        if self.index == -1 or self.index >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "No text box selected")
            return {'CANCELLED'}

        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        scene = context.scene
        if self.index < 0 or self.index >= len(scene.mixie_moodboard_textboxes):
            return

        tb = scene.mixie_moodboard_textboxes[self.index]
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=False)
        col.prop(tb, "font_size")
        col.separator(factor=0.4)

        col.prop(tb, "align")
        col.separator(factor=0.4)

        row = col.row(align=True)
        row.prop(tb, "bold", toggle=True)
        row.prop(tb, "italic", toggle=True)
        col.separator(factor=0.4)

        col.prop(tb, "text_color")
        col.prop(tb, "background_color")
        col.separator(factor=0.4)

        col.prop(tb, "width")
        col.prop(tb, "height")
        col.prop(tb, "rotation")

    def execute(self, context):
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_add_textbox,
    MIXIE_OT_moodboard_edit_textbox,
    MIXIE_OT_moodboard_update_textbox_properties,
    MIXIE_OT_moodboard_delete,
)
