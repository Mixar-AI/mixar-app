# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Group Operators

Operators for managing image groups in the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, FloatVectorProperty, IntProperty

class MIXIE_OT_create_group(Operator):
    """Create a new group from selected images"""
    bl_idname = "mixie.create_group"
    bl_label = "Create Group"
    bl_description = "Create a new group from selected images"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Group Name", default="New Group")
    color: FloatVectorProperty(name="Color", subtype='COLOR', default=(0.2, 0.6, 1.0, 1.0), size=4, min=0.0, max=1.0)

    def execute(self, context):
        scene = context.scene
        
        # Check if any images are selected
        selected_indices = [i for i, img in enumerate(scene.mixie_moodboard_images) if img.selected]
        if not selected_indices:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}

        # Create new group
        group = scene.mixie_moodboard_groups.add()
        group.name = self.name
        group.color = self.color
        group_idx = len(scene.mixie_moodboard_groups) - 1

        # Assign images to group
        for idx in selected_indices:
            scene.mixie_moodboard_images[idx].group_index = group_idx
            
        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"Created group '{self.name}' with {len(selected_indices)} images")
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

class MIXIE_OT_add_to_group(Operator):
    """Add selected images to the active group"""
    bl_idname = "mixie.add_to_group"
    bl_label = "Add to Group"
    bl_description = "Add selected images to a specific group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty(name="Group Index", default=-1)

    def execute(self, context):
        scene = context.scene
        
        if self.group_index < 0 or self.group_index >= len(scene.mixie_moodboard_groups):
            self.report({'ERROR'}, "Invalid group")
            return {'CANCELLED'}

        selected_imgs = [img for img in scene.mixie_moodboard_images if img.selected]
        if not selected_imgs:
            self.report({'WARNING'}, "No images selected")
            return {'CANCELLED'}

        count = 0
        for img in selected_imgs:
            if img.group_index != self.group_index:
                img.group_index = self.group_index
                count += 1
        
        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"Added {count} images to group")
        return {'FINISHED'}

class MIXIE_OT_remove_from_group(Operator):
    """Remove selected images from their group"""
    bl_idname = "mixie.remove_from_group"
    bl_label = "Remove from Group"
    bl_description = "Remove selected images from their current group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        selected_imgs = [img for img in scene.mixie_moodboard_images if img.selected]
        
        count = 0
        for img in selected_imgs:
            if img.group_index != -1:
                img.group_index = -1
                count += 1
                
        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"Removed {count} images from groups")
        return {'FINISHED'}

class MIXIE_OT_remove_from_specific_group(Operator):
    """Remove selected images from a specific group"""
    bl_idname = "mixie.remove_from_specific_group"
    bl_label = "Remove Selected from Group"
    bl_description = "Remove selected images from this specific group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty(name="Group Index", default=-1)

    def execute(self, context):
        scene = context.scene
        if self.group_index < 0:
            self.report({'ERROR'}, "Invalid group")
            return {'CANCELLED'}
            
        selected_imgs = [img for img in scene.mixie_moodboard_images if img.selected]
        
        count = 0
        for img in selected_imgs:
            if img.group_index == self.group_index:
                img.group_index = -1
                count += 1
        
        if count > 0 and context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"Removed {count} images from group")
        return {'FINISHED'}

class MIXIE_OT_delete_group(Operator):
    """Delete a group"""
    bl_idname = "mixie.delete_group"
    bl_label = "Delete Group"
    bl_description = "Delete a group (images remain)"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty(name="Group Index", default=-1)

    def execute(self, context):
        scene = context.scene
        if self.group_index < 0 or self.group_index >= len(scene.mixie_moodboard_groups):
            self.report({'ERROR'}, "Invalid group")
            return {'CANCELLED'}
        
        # Reset group index for images in this group
        # Also need to shift indices for images in higher groups
        deleted_group_idx = self.group_index
        
        for img in scene.mixie_moodboard_images:
            if img.group_index == deleted_group_idx:
                img.group_index = -1
            elif img.group_index > deleted_group_idx:
                img.group_index -= 1
                
        scene.mixie_moodboard_groups.remove(deleted_group_idx)
        
        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, "Group deleted")
        return {'FINISHED'}

class MIXIE_OT_select_group_images(Operator):
    """Select all images in a group"""
    bl_idname = "mixie.select_group_images"
    bl_label = "Select Group Images"
    bl_description = "Select all images belonging to this group"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: IntProperty(name="Group Index", default=-1)

    def execute(self, context):
        scene = context.scene
        if self.group_index < 0 or self.group_index >= len(scene.mixie_moodboard_groups):
            self.report({'ERROR'}, "Invalid group")
            return {'CANCELLED'}

        count = 0
        for img in scene.mixie_moodboard_images:
            if img.group_index == self.group_index:
                img.selected = True
                count += 1

        # Refresh moodboard to show selection
        if context.area:
            context.area.tag_redraw()

        self.report({'INFO'}, f"Selected {count} images in group")
        return {'FINISHED'}


class MIXIE_OT_ungroup(Operator):
    """Ungroup selected groups or groups containing selected images"""
    bl_idname = "mixie.ungroup"
    bl_label = "Ungroup"
    bl_description = "Dissolve selected groups and release their images (Alt+G)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Check if there are any groups to ungroup."""
        scene = context.scene
        if not hasattr(scene, 'mixie_moodboard_groups'):
            return False
        if len(scene.mixie_moodboard_groups) == 0:
            return False

        # Check for selected groups
        has_selected_group = any(g.selected for g in scene.mixie_moodboard_groups)
        if has_selected_group:
            return True

        # Check for selected images that belong to a group
        if hasattr(scene, 'mixie_moodboard_images'):
            has_grouped_selection = any(
                img.selected and img.group_index >= 0
                for img in scene.mixie_moodboard_images
            )
            if has_grouped_selection:
                return True

        return False

    def execute(self, context):
        scene = context.scene

        # Collect all group indices to dissolve
        groups_to_remove = set()

        # Add selected groups
        for i, group in enumerate(scene.mixie_moodboard_groups):
            if group.selected:
                groups_to_remove.add(i)

        # Add groups of selected images
        for img in scene.mixie_moodboard_images:
            if img.selected and img.group_index >= 0:
                groups_to_remove.add(img.group_index)

        if not groups_to_remove:
            self.report({'WARNING'}, "No groups to ungroup")
            return {'CANCELLED'}

        # Sort in reverse order so we can remove from highest index first
        sorted_groups = sorted(groups_to_remove, reverse=True)

        removed_count = 0
        for group_idx in sorted_groups:
            if group_idx >= len(scene.mixie_moodboard_groups):
                continue

            # Reset group index for all images in this group
            for img in scene.mixie_moodboard_images:
                if img.group_index == group_idx:
                    img.group_index = -1
                elif img.group_index > group_idx:
                    # Shift down indices for groups above the removed one
                    img.group_index -= 1

            # Remove the group
            scene.mixie_moodboard_groups.remove(group_idx)
            removed_count += 1

        # Trigger redraw
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        self.report({'INFO'}, f"Dissolved {removed_count} group(s)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_create_group,
    MIXIE_OT_add_to_group,
    MIXIE_OT_remove_from_group,
    MIXIE_OT_remove_from_specific_group,
    MIXIE_OT_delete_group,
    MIXIE_OT_select_group_images,
    MIXIE_OT_ungroup,
)
