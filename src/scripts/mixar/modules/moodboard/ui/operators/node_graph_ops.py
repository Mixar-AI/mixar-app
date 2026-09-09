# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""User-facing operators for moodboard inference nodes."""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core.graph_notice import post_graph_notice
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
    # Set only by the Shift+A Add-Node menu: create a standalone node with no
    # source, to be wired up afterwards. SKIP_SAVE for the same REGISTER reason
    # as the drop props above.
    allow_empty: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

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
                allow_empty=self.allow_empty,
            )
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Created {node.action_type.replace('_', ' ').title()} node")
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_add_menu(Operator):
    """Open the searchable Add-Node menu at the cursor (Shift+A)."""

    bl_idname = "mixie.moodboard_add_menu"
    bl_label = "Add Node"
    bl_description = "Add a new inference node at the cursor"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        scene = context.scene
        region = context.region
        if scene is not None:
            # This menu can create a node, so it must clear the link-drop
            # anchor like every other create-node entry point — otherwise a
            # dismissed noodle drag would place this node at that stale point.
            if hasattr(scene, "mixie_moodboard_link_drop_active"):
                scene.mixie_moodboard_link_drop_active = False
            # Remember the cursor so the chosen node spawns under it; the menu
            # forwards these as the create operator's drop position.
            if region is not None and hasattr(region, "view2d"):
                try:
                    view_x, view_y = region.view2d.region_to_view(
                        event.mouse_region_x, event.mouse_region_y
                    )
                    scene.mixie_moodboard_context_x = view_x
                    scene.mixie_moodboard_context_y = view_y
                except (AttributeError, TypeError):
                    pass
        bpy.ops.wm.call_menu(name="MIXIE_MT_moodboard_add")
        return {'FINISHED'}

    def execute(self, context):
        # Fallback when invoked without an event: the last recorded canvas
        # point is used.
        bpy.ops.wm.call_menu(name="MIXIE_MT_moodboard_add")
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
        from mixar.modules.moodboard.core.node_execution import (
            mark_run_failed,
            run_action_node,
        )
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
            # A node that is genuinely generating keeps its state; marking a
            # live job FAILED (e.g. on this second click) is a false alarm.
            marked = mark_run_failed(node, str(exc))
            self.report({'ERROR' if marked else 'WARNING'}, str(exc))
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        self.report({'INFO'}, "Node added to the generation queue")
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_toggle_node_edit(Operator):
    """Show or hide a finished node's settings and prompt"""

    bl_idname = "mixie.moodboard_toggle_node_edit"
    bl_label = "Edit Node"
    bl_description = (
        "Show this node's settings and prompt so it can be adjusted and run "
        "again; click again to cancel editing and go back to the result"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE for the same reason as run_action_node: this is a REGISTER
    # operator, so a remembered node_id would toggle a different card.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
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
        # Purely how the card is presented: the node keeps its state, its
        # result and its job history either way.
        node.edit_mode = not node.edit_mode
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_rename_node(Operator):
    """Name this node so it can be told apart from the others"""

    bl_idname = "mixie.moodboard_rename_node"
    bl_label = "Rename Node"
    bl_description = (
        "Give this node a name, shown in its header. Blank uses the node type"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE on both: this is a REGISTER operator, so anything the caller
    # leaves unset is refilled from the previous run -- a remembered node_id
    # would rename a different card, and a remembered name would prefill the
    # last one typed.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    name: bpy.props.StringProperty(
        name="Name",
        description="Shown in the node's header; blank uses the node type",
        default="",
        options={'SKIP_SAVE'},
    )

    def _node(self, context):
        from mixar.modules.moodboard.core.node_graph import (
            action_node_by_id,
            active_action_node,
        )

        return (
            action_node_by_id(context.scene, self.node_id)
            if self.node_id else active_action_node(context.scene)
        )

    def invoke(self, context, event):
        node = self._node(context)
        if node is None:
            # F2 lands here for whatever is selected. With no node it is a
            # reference image or movie the user means, and that rename is the
            # C++ in-place field (mixie_moodboard_ops_rename_media.cc), which
            # resolves the one selected reference itself and reports when
            # there is not exactly one.
            if not self.node_id:
                return bpy.ops.mixie.moodboard_rename_media()
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        # Resolve the id now: the popup's execute runs without an active-node
        # guarantee if the selection changes underneath it.
        self.node_id = node.node_id
        self.name = node.label
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        node = self._node(context)
        if node is None:
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        node.label = self.name.strip()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_disconnect_input(Operator):
    """Remove the link feeding one of a node's inputs"""

    bl_idname = "mixie.moodboard_disconnect_input"
    bl_label = "Disconnect Input"
    bl_description = "Remove the connection feeding this input"
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE for the usual REGISTER reason: remembered ids would disconnect
    # a socket the user never touched.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    socket_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import (
            action_node_by_id,
            refresh_node_socket_visibility,
        )

        scene = context.scene
        removed = 0
        # Reverse order: removing by index while iterating forwards would skip
        # the element after each removal.
        for index in reversed(range(len(scene.mixie_moodboard_links))):
            link = scene.mixie_moodboard_links[index]
            if link.to_node_id != self.node_id:
                continue
            if self.socket_id and link.to_socket != self.socket_id:
                continue
            scene.mixie_moodboard_links.remove(index)
            removed += 1
        if not removed:
            return {'CANCELLED'}
        # A repeatable input group grows one empty slot at a time, so a freed
        # socket has to be re-evaluated or the card keeps drawing a stale one.
        node = action_node_by_id(scene, self.node_id)
        if node is not None:
            refresh_node_socket_visibility(scene, node)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_moodboard_cancel_action_node(Operator):
    bl_idname = "mixie.moodboard_cancel_action_node"
    bl_label = "Cancel Generation"
    bl_description = "Cancel the generation this node is waiting on"
    bl_options = {'REGISTER'}

    # SKIP_SAVE: see MIXIE_OT_moodboard_run_action_node.node_id.
    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        from mixar.modules.moodboard.core.node_graph import (
            action_node_by_id,
            active_action_node,
        )
        from mixar.modules.moodboard.core.node_job_bridge import cancel_node_job

        node = (
            action_node_by_id(context.scene, self.node_id)
            if self.node_id else active_action_node(context.scene)
        )
        if node is None:
            self.report({'WARNING'}, "Select an inference node")
            return {'CANCELLED'}
        if cancel_node_job(node.node_id):
            self.report({'INFO'}, "Generation cancelled")
        elif node.state in {'QUEUED', 'RUNNING'}:
            # No live queue job backs this state (a stale .blend, or the queue
            # was cleared by a file load) — reconcile the node so it stops
            # claiming work that no longer exists.
            node.state = 'CANCELLED'
            self.report({'INFO'}, "This node was no longer generating")
        else:
            self.report({'WARNING'}, "This node is not generating")
            return {'CANCELLED'}
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
            # The status bar is somewhere the user is not looking: they are
            # watching the cursor they just released. Put the reason there too.
            post_graph_notice(context.scene, str(exc), self.to_node_id)
            self.report({'WARNING'}, str(exc))
            if context.area:
                context.area.tag_redraw()
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
    MIXIE_OT_moodboard_add_menu,
    MIXIE_OT_moodboard_run_action_node,
    MIXIE_OT_moodboard_toggle_node_edit,
    MIXIE_OT_moodboard_rename_node,
    MIXIE_OT_moodboard_disconnect_input,
    MIXIE_OT_moodboard_cancel_action_node,
    MIXIE_OT_moodboard_reset_node_params,
    MIXIE_OT_moodboard_delete_action_node,
    MIXIE_OT_moodboard_connect_nodes,
    MIXIE_OT_moodboard_select_asset_objects,
)
