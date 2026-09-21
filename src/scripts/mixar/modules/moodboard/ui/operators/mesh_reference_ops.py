# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Choose a scene mesh after placing a Moodboard reference card."""

import bpy
from bpy.types import Operator

from ...core.asset_nodes import assign_mesh_reference
from ...core.canvas_context import is_moodboard_context, redraw_moodboard_canvases
from ...core.node_graph import asset_node_by_id


# Enum callbacks receive OperatorProperties, not the operator instance, and
# cannot store Python attributes on it. Keep strings and object identities
# alive in a bounded per-card cache for the lifetime of each picker.
_searches = {}

# Blender's search popup is a fixed ten rows. A scene with a handful of
# meshes left that box almost empty and covering the card. A short list uses
# a menu that sizes to its rows; longer scenes keep the search.
_COMPACT_MESH_MENU_LIMIT = 8


def _search_key(props, context):
    return (context.scene.session_uid, props.node_id)


def _mesh_items(self, context):
    search = _searches.get(_search_key(self, context)) if context else None
    return search[0] if search else []


def _popup_compact_mesh_menu(context, node_id, objects):
    """A menu whose height follows the mesh count."""

    def draw(menu, _context):
        layout = menu.layout.mixar_surface(theme='ZEN', density='COMPACT')
        layout.operator_context = 'EXEC_DEFAULT'
        for obj in objects:
            props = layout.operator(
                "mixie.moodboard_select_mesh",
                text=obj.name,
                icon='OUTLINER_OB_MESH',
            )
            props.node_id = node_id
            props.object_name = obj.name

    context.window_manager.popup_menu(draw, title="Select Mesh")


class MIXIE_OT_moodboard_select_mesh(Operator):
    bl_idname = "mixie.moodboard_select_mesh"
    bl_label = "Select Mesh"
    bl_description = "Choose a mesh from this scene for the Moodboard node"
    bl_options = {'UNDO'}
    bl_property = "object_name"

    node_id: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    object_name: bpy.props.EnumProperty(name="Mesh", items=_mesh_items, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return is_moodboard_context(context)

    def invoke(self, context, event):
        objects = sorted((obj for obj in context.scene.objects if obj.type == 'MESH'),
                         key=lambda obj: obj.name.casefold())
        items = [(obj.name, obj.name, "Use this scene mesh", 'OUTLINER_OB_MESH', i)
                 for i, obj in enumerate(objects)]
        key = _search_key(self, context)
        _searches.pop(key, None)
        _searches[key] = (items, {obj.name: obj for obj in objects})
        while len(_searches) > 16:
            del _searches[next(iter(_searches))]
        if not _mesh_items(self, context):
            self.report({'WARNING'}, "No meshes in this scene. Add a mesh in the viewport first")
            return {'CANCELLED'}
        if len(objects) <= _COMPACT_MESH_MENU_LIMIT:
            _popup_compact_mesh_menu(context, self.node_id, objects)
            return {'INTERFACE'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        node = asset_node_by_id(context.scene, self.node_id)
        if node is None or not node.scene_mesh_reference:
            self.report({'WARNING'}, "This mesh reference is no longer available")
            return {'CANCELLED'}
        search = _searches.get(_search_key(self, context))
        obj = search[1].get(self.object_name) if search else None
        try:
            valid = obj is not None and context.scene.objects.get(obj.name) == obj
        except ReferenceError:
            valid = False
        if not valid:
            self.report({'WARNING'}, "That mesh is no longer in this scene. Select another mesh")
            return {'CANCELLED'}
        try:
            assign_mesh_reference(node, obj)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        redraw_moodboard_canvases()
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_select_mesh,)
