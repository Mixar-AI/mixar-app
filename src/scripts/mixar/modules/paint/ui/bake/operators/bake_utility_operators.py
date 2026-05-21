# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility operators for bake functionality - extracted from bake_to_layer_operators.py."""

import re
import time

import bmesh
import bpy
from bpy.props import StringProperty

from ....core.node.node_utils import get_active_mpaint_node, remove_node
from ....core.subtree.get_subtree import get_mask_tree, get_tree
from ....utils.blender_commons import (
    get_active_object,
    get_object_parent_layer_collections,
    get_scene_objects,
    get_user_preferences,
    get_viewport_context,
    set_active_object,
    set_object_hide,
    set_object_select,
)
from ..utils.bake_operators_helper import rebake_baked_images
from ...udim.udim_operators_helper import remove_udim_atlas_segment_by_name
from ..utils.bake_common import BaseBakeOperator


class MTryToSelectBakedVertexSelect(bpy.types.Operator):
    bl_idname = "wm.m_try_to_select_baked_vertex"
    bl_label = "Try to reselect baked selected vertex"
    bl_description = "Try to reselect baked selected vertex. It might give you wrong results if mesh number of vertex changed"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def execute(self, context):
        if not hasattr(context, "bake_info"):
            return {"CANCELLED"}

        bi = context.bake_info

        if len(bi.selected_objects) == 0:
            return {"CANCELLED"}

        if get_active_object().mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")

        scene_objs = get_scene_objects()
        objs = []
        for bso in bi.selected_objects:
            bsoo = bso.object

            if bsoo and bsoo not in objs:
                objs.append(bsoo)

        # Get actual selectable objects
        actual_selectable_objs = []
        for o in objs:
            layer_cols = get_object_parent_layer_collections(
                [], bpy.context.view_layer.layer_collection, o
            )

            # for lc in layer_cols:
            #    print(lc.name)

            if layer_cols and not any(
                [
                    lc
                    for lc in layer_cols
                    if lc.exclude or lc.hide_viewport or lc.collection.hide_viewport
                ]
            ):
                actual_selectable_objs.append(o)

        if len(actual_selectable_objs) == 0:
            self.report({"ERROR"}, "Cannot select the object!")
            return {"CANCELLED"}

        for obj in actual_selectable_objs:
            set_object_hide(obj, False)
            set_object_select(obj, True)

        set_active_object(actual_selectable_objs[0])

        bpy.ops.object.mode_set(mode="EDIT")
        # Mesh operators need viewport context
        viewport_ctx = get_viewport_context()

        if viewport_ctx:
            with bpy.context.temp_override(**viewport_ctx):
                bpy.ops.mesh.reveal()
                bpy.ops.mesh.select_all(action="DESELECT")
        else:
            # Fallback without context override
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action="DESELECT")

        for bso in bi.selected_objects:
            obj = bso.object

            if not obj or obj not in actual_selectable_objs:
                continue

            mesh = obj.data
            bm = bmesh.from_edit_mesh(mesh)

            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            if bi.selected_face_mode:
                context.tool_settings.mesh_select_mode[0] = False
                context.tool_settings.mesh_select_mode[1] = False
                context.tool_settings.mesh_select_mode[2] = True

                for bsv in bso.selected_vertex_indices:
                    try:
                        bm.faces[bsv.index].select = True
                    except:
                        pass
            else:
                context.tool_settings.mesh_select_mode[0] = True
                context.tool_settings.mesh_select_mode[1] = False
                context.tool_settings.mesh_select_mode[2] = False

                for bsv in bso.selected_vertex_indices:
                    try:
                        bm.verts[bsv.index].select = True
                    except:
                        pass

        return {"FINISHED"}


class MRemoveBakeInfoOtherObject(bpy.types.Operator):
    bl_idname = "wm.m_remove_bake_info_other_object"
    bl_label = "Remove other object info"
    bl_description = "Remove other object bake info, so it won't be automatically baked anymore if you choose to rebake"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def execute(self, context):
        if not hasattr(context, "other_object") or not hasattr(context, "bake_info"):
            return {"CANCELLED"}

        # if len(context.bake_info.other_objects) == 1:
        #    self.report({'ERROR'}, "Cannot delete, need at least one object!")
        #    return {'CANCELLED'}

        for i, oo in enumerate(context.bake_info.other_objects):
            if oo == context.other_object:
                context.bake_info.other_objects.remove(i)
                break

        return {"FINISHED"}


class MRemoveBakedEntity(bpy.types.Operator):
    bl_idname = "wm.m_remove_baked_entity"
    bl_label = "Remove Baked Layer/Mask"
    bl_description = "Remove baked layer/mask"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def execute(self, context):

        obj = get_active_object()
        mpup = get_user_preferences()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        entity = context.entity
        layer = None
        mask = None

        # Check entity
        m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity.path_from_id())
        m2 = re.match(r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

        tree = None
        baked_source = None
        if m1:
            layer = mp.layers[int(m1.group(1))]
            mask = None
            tree = get_tree(layer)
            baked_source = tree.nodes.get(layer.baked_source)
        elif m2:
            layer = mp.layers[int(m2.group(1))]
            mask = layer.masks[int(m2.group(2))]
            tree = get_mask_tree(mask)
            baked_source = tree.nodes.get(mask.baked_source)
        else:
            self.report({"ERROR"}, "Invalid context!")
            return {"CANCELLED"}

        if not baked_source:
            self.report({"ERROR"}, "No baked source found!")
            return {"CANCELLED"}

        image = baked_source.image if baked_source else None

        # Remove segment
        if image and entity.baked_segment_name != "":
            if image.yia.is_image_atlas:
                segment = image.yia.segments.get(entity.baked_segment_name)
                segment.unused = True
            elif image.yua.is_udim_atlas:
                remove_udim_atlas_segment_by_name(
                    image, entity.baked_segment_name, mp=mp
                )

            # Remove baked segment name since the data is removed
            entity.baked_segment_name = ""

        # Remove baked source
        remove_node(tree, entity, "baked_source")
        entity.use_baked = False

        # Remove baked mapping
        layer_tree = get_tree(layer)
        remove_node(layer_tree, entity, "baked_mapping")

        return {"FINISHED"}


class MRebakeBakedImages(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_rebake_baked_images"
    bl_label = "Rebake All Baked Images"
    bl_description = "Rebake all baked images used by all layers and masks"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def invoke(self, context, event):
        if get_user_preferences().skip_property_popups and not event.shift:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.label(text="Rebaking all baked images can take a while to process", icon="ERROR")
        col.label(text="Are you sure you want to continue?", icon="BLANK1")

    def execute(self, context):
        T = time.time()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        baked_counts = rebake_baked_images(mp)

        if baked_counts == 0:
            self.report({"ERROR"}, "No baked layer/mask used!")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            "Rebaking all baked layers & masks is done in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )
        return {"FINISHED"}


class MRebakeSpecificLayers(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_rebake_specific_layers"
    bl_label = "Rebake Specific Layers"
    bl_description = "Rebake specific layers (FOR INTERNAL USE ONLY)"
    bl_options = {"REGISTER"}

    layer_ids: StringProperty(
        name="Layer Indices",
        description="Layer indices in form of list of integer converted to string",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def execute(self, context):
        T = time.time()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        layers = []
        if self.layer_ids != "":
            import ast

            ids = ast.literal_eval(self.layer_ids)
            layers = [l for i, l in enumerate(mp.layers) if i in ids]

        rebake_baked_images(mp, specific_layers=layers)

        return {"FINISHED"}


classes = (
    MTryToSelectBakedVertexSelect,
    MRemoveBakeInfoOtherObject,
    MRemoveBakedEntity,
    MRebakeBakedImages,
    MRebakeSpecificLayers,
)
