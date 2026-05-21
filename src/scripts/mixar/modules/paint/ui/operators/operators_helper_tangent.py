# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tangent sign vertex color helper functions.

Functions for managing tangent sign hacks and vertex colors.
"""

import bpy

from ...core.element.create_vcol import new_vertex_color
from ...core.element.update_uv import set_active_uv_layer
from ...core.element.update_vcol import remove_tangent_sign_vcol
from ...core.io.connections import set_normal_backface_flip
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ...core.layer.layer_utils import get_uv_layers
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.check_nodes import check_mp_linear_nodes
from ...core.node.node_utils import get_active_mpaint_node, get_vertex_colors
from ...ui.modifier.modifier_utils import check_mp_modifier_linear_nodes
from ...utils.blender_commons import (
    get_active_object,
    get_scene_objects,
    is_bl_newer_than,
    remove_datablock,
    remove_mesh_obj,
    set_active_mode,
)
from ...utils.constants import TANGENT_SIGN_PREFIX

# Delayed import to avoid circular dependency
def _get_update_layer_preview_mode():
    from .operators_helper_preview import update_layer_preview_mode
    return update_layer_preview_mode

def update_flip_backface(self, context):
    """Update backface flip settings for all channels and UVs.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    mp = self
    group_tree = mp.id_data

    for ch in mp.channels:
        baked_normal_flip = group_tree.nodes.get(ch.baked_normal_flip)
        if baked_normal_flip:
            set_normal_backface_flip(baked_normal_flip, mp.enable_backface_always_up)

        baked_normal_prep = group_tree.nodes.get(ch.baked_normal_prep)
        if baked_normal_prep:
            baked_normal_prep.inputs['Backface Always Up'].default_value = 1.0 if mp.enable_backface_always_up else 0.0

    for uv in mp.uvs:
        #tangent_flip = group_tree.nodes.get(uv.tangent_flip)
        #if tangent_flip:
        #    set_tangent_backface_flip(tangent_flip, mp.enable_backface_always_up)

        #bitangent_flip = group_tree.nodes.get(uv.bitangent_flip)
        #if bitangent_flip:
        #    set_bitangent_backface_flip(bitangent_flip, mp.enable_backface_always_up)

        tangent_process = group_tree.nodes.get(uv.tangent_process)
        if tangent_process:
            tangent_process.inputs['Backface Always Up'].default_value = 1.0 if mp.enable_backface_always_up else 0.0


def update_enable_tangent_sign_hacks(self, context):
    """Update when tangent sign hacks are enabled/disabled.

    Clears tangent sign attribute and removes tangent sign vertex colors.

    Args:
        self: UI property group.
        context: Blender context.
    """
    node = get_active_mpaint_node()
    tree = node.node_tree
    mp = tree.mp
    #mpui = context.window_manager.mpui
    mpui = self
    obj = get_active_object()

    for uv in mp.uvs:
        tangent_process = tree.nodes.get(uv.tangent_process)
        if tangent_process:
            tsign = tangent_process.node_tree.nodes.get('_tangent_sign')
            tsign.attribute_name = ''
            remove_tangent_sign_vcol(obj, uv.name)

def refresh_tangent_sign_vcol(obj, uv_name):
    """Refresh tangent sign vertex color for object and related objects.

    Args:
        obj: Object to refresh tangent sign vcol for.
        uv_name (str): UV layer name.

    Returns:
        VertexColor: The refreshed vertex color layer.
    """
    vcol = actual_refresh_tangent_sign_vcol(obj, uv_name)

    mat = obj.active_material

    # Flag for already processed mesh
    meshes_done = [obj.data]

    obs = get_all_objects_with_same_materials(mat)
    for ob in obs:
        if ob != obj and ob.data not in meshes_done:
            other_v = actual_refresh_tangent_sign_vcol(ob, uv_name)
            meshes_done.append(ob.data)

    return vcol

def actual_refresh_tangent_sign_vcol(obj, uv_name):
    """Actually refresh tangent sign vertex color for a single object.

    Calculates tangent data and stores bitangent sign in vertex colors.
    Handles ngon meshes using temporary triangulation and data transfer.

    Args:
        obj: Object to refresh tangent sign vcol for.
        uv_name (str): UV layer name.

    Returns:
        VertexColor: The refreshed vertex color layer, or None if failed.
    """
    if obj.type != 'MESH': return None

    # Cannot do this in edit mode
    ori_obj = get_active_object()
    ori_mode = ori_obj.mode
    if ori_mode != 'OBJECT':
        set_active_mode('OBJECT')

    # Select only relevant object
    ori_selects = [o for o in bpy.context.selected_objects]
    bpy.ops.object.select_all(action='DESELECT')

    if is_bl_newer_than(2, 80): 
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    else: 
        obj.select = True
        bpy.context.scene.objects.active = obj

    # Set vertex color of bitangent sign
    uv_layers = get_uv_layers(obj)

    uv_layer = uv_layers.get(uv_name)
    if uv_layer:

        # Set uv as active
        ori_layer_name = uv_layers.active.name
        uv_layers.active = uv_layer

        # Get vertex color
        vcols = get_vertex_colors(obj)
        vcol = vcols.get(TANGENT_SIGN_PREFIX + uv_name)
        if not vcol:
            try: 
                vcol = new_vertex_color(obj, TANGENT_SIGN_PREFIX + uv_name)
            except: 
                recover_tangent_sign_process(ori_obj, ori_mode, ori_selects)
                return None

            # Set default color to be white
            if is_bl_newer_than(2, 80):
                for d in vcol.data: 
                    d.color = (1.0, 1.0, 1.0, 1.0)
            else: 
                for d in vcol.data: 
                    d.color = (1.0, 1.0, 1.0)

        # Use try except because ngon can cause error 
        try:
            # Calc tangents
            obj.data.calc_tangents()

            # Get vcol again after calculate tangent to prevent error
            vcol = vcols.get(TANGENT_SIGN_PREFIX + uv_name)

            # Set tangent sign to vertex color
            i = 0
            for poly in obj.data.polygons:
                for idx in poly.loop_indices:
                    vert = obj.data.loops[idx]
                    bs = max(vert.bitangent_sign, 0.0)
                    # Invert bitangent sign so the default value is 0.0 rather than 1.0
                    bs = 1.0 - bs
                    if is_bl_newer_than(2, 80):
                        vcol.data[i].color = (bs, bs, bs, 1.0)
                    else: vcol.data[i].color = (bs, bs, bs)
                    i += 1

        # If using ngon, need a temporary mesh
        except:

            # Remember selection
            if is_bl_newer_than(2, 80):
                ori_select = [o for o in bpy.context.view_layer.objects if o.select_get()]
            else: ori_select = [o for o in bpy.context.scene.objects if o.select]

            # If object has multi users, get all related objects
            related_objs = []
            if obj.data.users > 1:
                for o in get_scene_objects():
                    if o.data == obj.data and o != obj:
                        related_objs.append(o)

                # Make object data single user
                obj.data = obj.data.copy()

            temp_ob = obj.copy()
            temp_ob.data = obj.data.copy()
            temp_ob.name = '___TEMP__'

            if is_bl_newer_than(2, 80):
                bpy.context.scene.collection.objects.link(temp_ob)
                bpy.context.view_layer.objects.active = temp_ob
            else: 
                bpy.context.scene.objects.link(temp_ob)
                bpy.context.scene.objects.active = temp_ob

            # Triangulate ngon faces on temp object
            bpy.ops.object.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_face_by_sides(number=4, type='GREATER')
            bpy.ops.mesh.quads_convert_to_tris()
            bpy.ops.mesh.tris_convert_to_quads()
            bpy.ops.object.mode_set(mode='OBJECT')

            # Remove all modifiers on temp object
            for mod in temp_ob.modifiers:
                bpy.ops.object.modifier_remove(modifier=mod.name)

            # Calc tangents
            temp_ob.data.calc_tangents()

            # Set tangent sign to vertex color
            tvcols = get_vertex_colors(temp_ob)
            temp_vcol = tvcols.get(TANGENT_SIGN_PREFIX + uv_name)
            i = 0
            for poly in temp_ob.data.polygons:
                for idx in poly.loop_indices:
                    vert = temp_ob.data.loops[idx]
                    bs = max(vert.bitangent_sign, 0.0)
                    # Invert bitangent sign so the default value is 0.0 rather than 1.0
                    bs = 1.0 - bs
                    if is_bl_newer_than(2, 80):
                        temp_vcol.data[i].color = (bs, bs, bs, 1.0)
                    else: temp_vcol.data[i].color = (bs, bs, bs)
                    i += 1

            # Set active object back to the original mesh
            if is_bl_newer_than(2, 80):
                bpy.context.view_layer.objects.active = obj
            else: bpy.context.scene.objects.active = obj

            # Number of original modifiers
            num_mods = len(obj.modifiers)

            # Remember original enabled modifiers
            ori_show_render_mods = []
            ori_show_viewport_mods = []
            for m in obj.modifiers:
                ori_show_viewport_mods.append(m.show_viewport)
                ori_show_render_mods.append(m.show_render)
                m.show_viewport = False
                m.show_render = False
            
            # Add data transfer to original object
            mod_name = 'Transferz'
            mod = obj.modifiers.new(mod_name, 'DATA_TRANSFER')

            # Move data transfer modifier to the top
            #for i in range(len(obj.modifiers)-1):
            for i in range(num_mods):
                bpy.ops.object.modifier_move_up(modifier=mod_name)
                
            # Set transfer object
            mod.object = temp_ob
            mod.use_loop_data = True
            mod.data_types_loops = {'VCOL'}
            
            # Apply modifier
            bpy.ops.object.modifier_apply(modifier=mod_name)

            # Recover original enabled modifiers
            for i, m in enumerate(obj.modifiers):
                if ori_show_viewport_mods[i]:
                    m.show_viewport = ori_show_viewport_mods[i]
                if ori_show_render_mods[i]:
                    m.show_render = ori_show_render_mods[i]

            # Delete temp object
            remove_mesh_obj(temp_ob)

            # Set back original select
            for o in ori_select:
                if is_bl_newer_than(2, 80):
                    o.select_set(True)
                else: o.select = True

            # Bring object data to related objects
            if related_objs:
                ori_mesh = related_objs[0].data
                ori_name = ori_mesh.name
                for o in related_objs:
                    o.data = obj.data

                remove_datablock(bpy.data.meshes, ori_mesh)
                o.data.name = ori_name

        # Recover active uv
        set_active_uv_layer(obj, ori_layer_name)

        # Recovers
        recover_tangent_sign_process(ori_obj, ori_mode, ori_selects)

        # Get vcol again to make sure the data is consistent
        vcols = get_vertex_colors(obj)
        vcol = vcols.get(TANGENT_SIGN_PREFIX + uv_name)

        return vcol

    # Recovers
    recover_tangent_sign_process(ori_obj, ori_mode, ori_selects)

    return None


def update_use_linear_blending(self, context):
    """Update when linear blending setting changes.

    Updates modifier nodes, channel nodes, and layer preview to use linear blending.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    check_mp_modifier_linear_nodes(self)
    check_start_end_root_ch_nodes(self.id_data)
    check_mp_linear_nodes(self)

    if self.layer_preview_mode:
        _get_update_layer_preview_mode()(self, context)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)


def recover_tangent_sign_process(ori_obj, ori_mode, ori_selects):
    """Recover original object selection and mode after tangent sign process.

    Args:
        ori_obj: Original active object.
        ori_mode (str): Original object mode.
        ori_selects (list): List of originally selected objects.
    """
    # Recover selected and active objects
    bpy.ops.object.select_all(action='DESELECT')
    for o in ori_selects:
        o.select_set(True)

    bpy.context.view_layer.objects.active = ori_obj

    # Back to original mode
    if ori_mode != ori_obj.mode:
        bpy.ops.object.mode_set(mode=ori_mode)
