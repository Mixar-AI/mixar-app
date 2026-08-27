# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""User-facing operators for moodboard inference nodes."""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.ui.moodboard_graph_properties import ACTION_TYPES


class MIXIE_OT_moodboard_create_connected_action(Operator):
    bl_idname = "mixie.moodboard_create_connected_action"
    bl_label = "Create Connected Node"
    bl_options = {'REGISTER', 'UNDO'}

    action_type: bpy.props.EnumProperty(items=ACTION_TYPES)
    source_node_id: bpy.props.StringProperty(default="")
    # SKIP_SAVE: this is a REGISTER operator, so any property the caller leaves
    # unset is re-filled from the last run. Without it, one node created by
    # dropping a noodle would pin every later menu entry to that same spot.
    use_drop_position: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    drop_x: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})
    drop_y: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import create_connected_action

        try:
            node = create_connected_action(
                context.scene,
                self.action_type,
                self.source_node_id,
                drop_position=(
                    (self.drop_x, self.drop_y) if self.use_drop_position else None
                ),
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Created {node.action_type.replace('_', ' ').title()} node")
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_run_action_node(Operator):
    bl_idname = "mixie.moodboard_run_action_node"
    bl_label = "Run Node"
    bl_description = "Submit this inference node to the generation queue"
    bl_options = {'REGISTER'}

    # SKIP_SAVE: this is a REGISTER operator, so saved last-used properties
    # are re-applied to any invocation that passes no properties — a stale
    # remembered node_id would silently re-run a different node.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    edit_before_run: bpy.props.BoolProperty(
        default=False,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        from mixar.modules.moodboard.core.node_execution import run_action_node
        from mixar.modules.moodboard.core.node_graph import (
            action_node_by_id,
            active_action_node,
        )

        node = (
            action_node_by_id(context.scene, self.node_id)
            if self.node_id else active_action_node(context.scene)
        )
        if node is None:
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        if self.edit_before_run:
            if node.state in {'QUEUED', 'RUNNING'}:
                self.report({'WARNING'}, "This node is already running")
                return {'CANCELLED'}
            node.state = 'DRAFT'
            node.job_id = ""
            node.error = ""
            self.report({'INFO'}, "Edit the prompt, then press Enter or Generate")
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        try:
            run_action_node(context, node, self)
        except Exception as exc:
            node.state = 'FAILED'
            node.error = str(exc)
            self.report({'ERROR'}, str(exc))
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        self.report({'INFO'}, "Node added to the generation queue")
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_reset_node_params(Operator):
    bl_idname = "mixie.moodboard_reset_node_params"
    bl_label = "Reset Settings"
    bl_description = "Restore this node's settings to the model defaults"
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE: see MIXIE_OT_moodboard_run_action_node.node_id.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import (
            action_node_by_id,
            active_action_node,
        )
        from mixar.modules.moodboard.core.node_schema import reset_node_parameters

        node = (
            action_node_by_id(context.scene, self.node_id)
            if self.node_id else active_action_node(context.scene)
        )
        if node is None:
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        if node.state in {'QUEUED', 'RUNNING'}:
            self.report({'WARNING'}, "This node is already running")
            return {'CANCELLED'}
        reset_node_parameters(node)
        self.report({'INFO'}, "Settings reset to defaults")
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_delete_action_node(Operator):
    bl_idname = "mixie.moodboard_delete_action_node"
    bl_label = "Delete Node"
    bl_options = {'REGISTER', 'UNDO'}

    node_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.moodboard.core.node_deletion import remove_action_node
        from mixar.modules.moodboard.core.node_graph import active_action_node

        node_id = self.node_id
        if not node_id:
            node = active_action_node(context.scene)
            node_id = node.node_id if node else ""
        if not node_id or not remove_action_node(context.scene, node_id):
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_connect_nodes(Operator):
    bl_idname = "mixie.moodboard_connect_nodes"
    bl_label = "Connect Moodboard Nodes"
    bl_description = "Connect an output to a compatible backend-defined input"
    bl_options = {'REGISTER', 'UNDO'}

    from_node_id: bpy.props.StringProperty(default="")
    to_node_id: bpy.props.StringProperty(default="")
    # Empty means "whichever input fits": a noodle released on a card's body
    # rather than precisely on one of its sockets still has an unambiguous
    # target, so it resolves to the first free compatible slot.
    to_socket: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import (
            connect_nodes,
            connect_to_next_input,
        )

        try:
            if self.to_socket:
                connect_nodes(
                    context.scene,
                    self.from_node_id,
                    self.to_node_id,
                    self.to_socket,
                )
            else:
                connect_to_next_input(
                    context.scene, self.from_node_id, self.to_node_id
                )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_select_asset_objects(Operator):
    bl_idname = "mixie.moodboard_select_asset_objects"
    bl_label = "Select 3D Asset"
    bl_options = {'REGISTER'}

    node_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import asset_node_by_id

        node = asset_node_by_id(context.scene, self.node_id)
        if node is None:
            return {'CANCELLED'}
        # Deselect by iterating the view layer rather than calling
        # bpy.ops.object.select_all: this operator runs from the MIXIE space,
        # where that operator's poll fails and raises an uncaught RuntimeError.
        view_layer = context.view_layer
        try:
            for obj in view_layer.objects:
                obj.select_set(False)
        except (AttributeError, RuntimeError) as exc:
            self.report({'WARNING'}, f"Could not update the selection: {exc}")
            return {'CANCELLED'}
        selected = []
        for name in node.object_names.split(","):
            obj = bpy.data.objects.get(name.strip())
            if obj is not None and obj.name in view_layer.objects:
                obj.select_set(True)
                selected.append(obj)
        if selected:
            view_layer.objects.active = selected[0]
        self.report({'INFO'}, f"Selected {len(selected)} object(s)")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_create_connected_action,
    MIXIE_OT_moodboard_run_action_node,
    MIXIE_OT_moodboard_reset_node_params,
    MIXIE_OT_moodboard_delete_action_node,
    MIXIE_OT_moodboard_connect_nodes,
    MIXIE_OT_moodboard_select_asset_objects,
)
