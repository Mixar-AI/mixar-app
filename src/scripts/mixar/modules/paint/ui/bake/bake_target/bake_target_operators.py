# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ....core.node.node_utils import get_active_mpaint_node, remove_node
from ....utils.blender_commons import get_active_object, get_unique_name
from ....utils.common import get_addon_title, split_layout
from .bake_target_operators_helper import update_new_bake_target_preset


class MNewBakeTarget(bpy.types.Operator):
    bl_idname = "wm.m_new_bake_target"
    bl_label = "New Bake Target"
    bl_description = "New bake target"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(
        name="New Bake Target Name", description="New bake target name", default=""
    )

    preset: EnumProperty(
        name="Bake Target Preset",
        description="Customm bake target preset",
        items=(
            ("BLANK", "Blank", ""),
            ("ORM", "GLTF ORM", ""),
            ("DX_NORMAL", "DirectX Normal", ""),
        ),
        default="BLANK",
        update=update_new_bake_target_preset,
    )

    use_float: BoolProperty(
        name="32-bit Float", description="Use 32-bit float image", default=False
    )

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Parameters:
            context: Blender context

        Returns:
            bool: True if active mpaint node exists
        """
        return get_active_mpaint_node()

    def invoke(self, context, event):
        """Initialize operator properties and display dialog.

        Parameters:
            context: Blender context
            event: Event that triggered the operator

        Returns:
            set: Operator return value
        """
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        tree_name = tree.name.replace(get_addon_title() + " ", "")
        # self.name = get_unique_name(tree_name + ' Bake Target', mp.bake_targets)
        self.name = get_unique_name(tree_name + " Bake Target", bpy.data.images)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        """Draw operator UI in dialog.

        Parameters:
            context: Blender context

        Returns:
            None
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== NEW BAKE TARGET ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="New Bake Target", icon="IMAGE_DATA")

        col.separator(factor=1.2)

        # Name
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        split.prop(self, "name", text="")
        col.separator(factor=0.4)

        # Preset
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Preset:")
        split.prop(self, "preset", text="")
        col.separator(factor=0.4)

        # Use Float
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="32-bit Float:")
        split.prop(self, "use_float", text="")
        col.separator(factor=0.4)

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        """Create new bake target with configured properties.

        Parameters:
            context: Blender context

        Returns:
            set: {'FINISHED'} on success
        """
        wm = context.window_manager
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        mpui = wm.mpui

        bt = mp.bake_targets.add()
        bt.name = self.name
        bt.use_float = self.use_float
        bt.a.default_value = 1.0

        if self.preset == "ORM":
            for ch in mp.channels:
                if ch.name in {"Ambient Occlusion", "AO"}:
                    bt.r.channel_name = ch.name
                elif ch.name in {"Roughness", "R"}:
                    bt.g.channel_name = ch.name
                elif ch.name in {"Metallic", "Metalness", "M"}:
                    bt.b.channel_name = ch.name
                bt.r.default_value = 1.0

        elif self.preset == "DX_NORMAL":
            for ch in mp.channels:
                if ch.type == "NORMAL":
                    bt.r.channel_name = ch.name
                    bt.g.channel_name = ch.name
                    bt.b.channel_name = ch.name

                    bt.r.subchannel_index = "0"
                    bt.g.subchannel_index = "1"
                    bt.b.subchannel_index = "2"

                    bt.g.invert_value = True

        mp.active_bake_target_index = len(mp.bake_targets) - 1

        mpui.bake_target_ui.expand_content = True
        mpui.need_update = True
        # wm.mptimer.time = str(time.time())

        # Update panel
        context.area.tag_redraw()

        return {"FINISHED"}


class MRemoveBakeTarget(bpy.types.Operator):
    bl_idname = "wm.m_remove_bake_target"
    bl_label = "Remove Bake Target"
    bl_description = "Remove bake target"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Parameters:
            context: Blender context

        Returns:
            bool: True if active mpaint node exists
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Remove the active bake target and its associated nodes.

        Parameters:
            context: Blender context

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on error
        """
        wm = context.window_manager
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        try:
            bt = mp.bake_targets[mp.active_bake_target_index]
        except:
            return {"CANCELLED"}

        # Remove related nodes
        remove_node(tree, bt, "image_node")

        # Remove bake target
        mp.bake_targets.remove(mp.active_bake_target_index)

        if len(mp.bake_targets) > 0:
            mp.active_bake_target_index = len(mp.bake_targets) - 1

        # Update panel
        context.area.tag_redraw()

        return {"FINISHED"}


class MCopyBakeTarget(bpy.types.Operator):
    bl_idname = "wm.m_copy_bake_target"
    bl_label = "Copy Bake Target"
    bl_description = "Copy Bake Target"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Parameters:
            context: Blender context

        Returns:
            bool: True if active mpaint node exists with valid bake target
        """
        node = get_active_mpaint_node()
        if not node:
            return False

        group_tree = node.node_tree
        mp = group_tree.mp

        return (
            get_active_object()
            and len(mp.bake_targets) > 0
            and mp.active_bake_target_index >= 0
        )

    def execute(self, context):
        """Copy active bake target to clipboard.

        Parameters:
            context: Blender context

        Returns:
            set: {'FINISHED'} on success
        """
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        wmp = context.window_manager.mpprops

        bt = mp.bake_targets[mp.active_bake_target_index]

        wmp.clipboard_bake_target.clear()
        cbt = wmp.clipboard_bake_target.add()

        cbt.name = bt.name
        cbt.use_float = bt.use_float
        cbt.data_type = bt.data_type

        cbt.r.channel_name = bt.r.channel_name
        cbt.r.subchannel_index = bt.r.subchannel_index
        cbt.r.default_value = bt.r.default_value
        cbt.r.normal_type = bt.r.normal_type
        cbt.r.invert_value = bt.r.invert_value

        cbt.g.channel_name = bt.g.channel_name
        cbt.g.subchannel_index = bt.g.subchannel_index
        cbt.g.default_value = bt.g.default_value
        cbt.g.normal_type = bt.g.normal_type
        cbt.g.invert_value = bt.g.invert_value

        cbt.b.channel_name = bt.b.channel_name
        cbt.b.subchannel_index = bt.b.subchannel_index
        cbt.b.default_value = bt.b.default_value
        cbt.b.normal_type = bt.b.normal_type
        cbt.b.invert_value = bt.b.invert_value

        cbt.a.channel_name = bt.a.channel_name
        cbt.a.subchannel_index = bt.a.subchannel_index
        cbt.a.default_value = bt.a.default_value
        cbt.a.normal_type = bt.a.normal_type
        cbt.a.invert_value = bt.a.invert_value

        return {"FINISHED"}


class MPasteBakeTarget(bpy.types.Operator):
    bl_idname = "wm.m_paste_bake_target"
    bl_label = "Paste Bake Target As New"
    bl_description = "Paste Bake Target"
    bl_options = {"UNDO"}

    paste_as_new: BoolProperty(name="Paste As New Bake Target", default=True)

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Parameters:
            context: Blender context

        Returns:
            bool: True if clipboard has bake target data
        """
        node = get_active_mpaint_node()

        wmp = context.window_manager.mpprops
        has_clipboard = len(wmp.clipboard_bake_target) > 0

        return get_active_object() and node and has_clipboard

    def execute(self, context):
        """Paste bake target from clipboard.

        Parameters:
            context: Blender context

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on error
        """
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        wmp = context.window_manager.mpprops

        if not self.paste_as_new and (
            mp.active_bake_target_index < 0
            or mp.active_bake_target_index >= len(mp.bake_targets)
            or len(mp.bake_targets) == 0
        ):
            self.report({"ERROR"}, "Cannot paste values, no bake target selected")
            return {"CANCELLED"}

        cbt = wmp.clipboard_bake_target[0]

        if self.paste_as_new:
            name = get_unique_name(cbt.name, mp.bake_targets)
            bt = mp.bake_targets.add()
            bt.name = name
        else:
            bt = mp.bake_targets[mp.active_bake_target_index]

        bt.use_float = cbt.use_float
        bt.data_type = cbt.data_type

        bt.r.channel_name = cbt.r.channel_name
        bt.r.subchannel_index = cbt.r.subchannel_index
        bt.r.default_value = cbt.r.default_value
        bt.r.normal_type = cbt.r.normal_type
        bt.r.invert_value = cbt.r.invert_value

        bt.g.channel_name = cbt.g.channel_name
        bt.g.subchannel_index = cbt.g.subchannel_index
        bt.g.default_value = cbt.g.default_value
        bt.g.normal_type = cbt.g.normal_type
        bt.g.invert_value = cbt.g.invert_value

        bt.b.channel_name = cbt.b.channel_name
        bt.b.subchannel_index = cbt.b.subchannel_index
        bt.b.default_value = cbt.b.default_value
        bt.b.normal_type = cbt.b.normal_type
        bt.b.invert_value = cbt.b.invert_value

        bt.a.channel_name = cbt.a.channel_name
        bt.a.subchannel_index = cbt.a.subchannel_index
        bt.a.default_value = cbt.a.default_value
        bt.a.normal_type = cbt.a.normal_type
        bt.a.invert_value = cbt.a.invert_value

        return {"FINISHED"}


classes = (
    MNewBakeTarget,
    MRemoveBakeTarget,
    MCopyBakeTarget,
    MPasteBakeTarget,
)
