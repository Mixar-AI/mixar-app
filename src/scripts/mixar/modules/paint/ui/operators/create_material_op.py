# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create material operator for Mixar layers system"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from mathutils import Vector

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.io.utils.bsdf_connections import commit_mp_material
from ...core.layer.create_channels import create_new_mp_channel
from ...core.node.get_nodes import get_closest_bsdf_backward, get_material_output
from ...core.node.create_nodes import create_new_group_tree, simple_new_mix_node
from ...utils.blender_commons import get_active_material, get_active_object
from ...utils.common import get_addon_title, get_mix_color_indices
from ...utils.constants import AO_MULTIPLY, MP_GROUP_PREFIX
from ...utils.preferences import get_mixar_paint_preferences
from ..utils.ui_refresh import request_ui_refresh
from .operators_helper import check_all_channel_ios, set_input_default_value


class LAYERS_OT_AOBakePrompt(Operator):
    """Prompt user to bake AO after material creation"""

    bl_idname = "layers.ao_bake_prompt"
    bl_label = "Bake Ambient Occlusion"
    bl_description = "Bake ambient occlusion map for accurate shading"
    bl_options = {"REGISTER", "INTERNAL"}

    def invoke(self, context, event):
        """Show confirmation dialog."""
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        """Draw the AO bake prompt dialog."""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # Question
        question_row = main_col.row(align=True)
        question_row.scale_y = 1.3
        question_row.label(text="Bake Ambient Occlusion now?", icon='SHADING_RENDERED')

        main_col.separator(factor=0.8)

        # Info box
        info_box = main_col.box()
        info_col = info_box.column(align=True)
        info_col.scale_y = 1.1
        info_col.label(text="AO baking creates realistic shadows in crevices.", icon='INFO')
        info_col.separator(factor=0.3)
        info_col.label(text="Settings: 32 samples, denoise enabled")

        main_col.separator(factor=0.5)

        # Note
        note_row = main_col.row(align=True)
        note_row.label(text="You can also bake AO later from the Baking panel.", icon='TIME')

    def execute(self, context):
        """Invoke the AO bake operator to update existing Fill layer."""
        # Invoke the bake-to-layer operator with AO type
        # Use PREVIEW mode with apply_to_fill_layer to update Fill layer's AO channel
        bpy.ops.wm.m_bake_to_layer(
            'INVOKE_DEFAULT',
            type='AO',
            target_type='PREVIEW',
            apply_to_fill_layer=True
        )
        return {'FINISHED'}


class LAYERS_OT_CreateMaterial(Operator):
    """Create layer based material"""

    bl_idname = "layers.create_material"
    bl_label = "Create Layer Based Material"
    bl_description = "Initialize layer based material system for this object"
    bl_options = {"REGISTER", "UNDO"}

    tree_name: StringProperty(name="Name", description="Name of the material tree")
    set_material_name_from_tree_name: BoolProperty(
        name="Also Set Material Name",
        description="Also set material name from tree name",
        default=False,
    )
    type: EnumProperty(
        name="Type",
        items=(
            ("BSDF_PRINCIPLED", "Principled", ""),
            ("BSDF_DIFFUSE", "Diffuse", ""),
            ("EMISSION", "Emission", ""),
        ),
        default="BSDF_PRINCIPLED",
    )
    color: BoolProperty(name="Color", default=True)
    ao: BoolProperty(name="Ambient Occlusion", default=False)
    metallic: BoolProperty(name="Metallic", default=True)
    roughness: BoolProperty(name="Roughness", default=True)
    normal: BoolProperty(name="Normal", default=True)
    use_linear_blending: BoolProperty(
        name="Use Linear Color Blending",
        description="Use more accurate linear color blending",
        default=True,
    )
    switch_to_material_view: BoolProperty(
        name="Switch to Material View",
        description="Switch to material view so the node setup is automatically visible",
        default=True,
    )
    create_default_layer: BoolProperty(
        name="Create Default Layer",
        description=(
            "Create the default fill layer after the material is set up. "
            "Disable for scripted/agent flows that build their own layers, "
            "so the stack starts empty instead of carrying a leftover fill layer"
        ),
        default=True,
    )
    target_bsdf_name: StringProperty(default="")
    not_on_material_view: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed."""
        obj = context.active_object
        return obj and obj.type == "MESH"

    def invoke(self, context, event):
        """Initialize material creation settings and show dialog."""
        space = context.space_data
        obj = get_active_object()
        mat = get_active_material(obj)
        valid_bsdf_types = ["BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION"]

        self.tree_name = MP_GROUP_PREFIX + (mat.name if mat else obj.name)
        self.target_bsdf_name = ""
        output = get_material_output(mat)
        if output:
            bsdf_node = get_closest_bsdf_backward(output, valid_bsdf_types)
            if bsdf_node:
                self.type = bsdf_node.type
                self.target_bsdf_name = bsdf_node.name

        self.not_on_material_view = (
            space.type == "VIEW_3D"
            and space.shading.type not in {"MATERIAL", "RENDERED"}
        )
        # Execute removes all existing nodes; warn in the dialog when they exist
        self._will_remove_nodes = bool(
            mat and mat.node_tree and len(mat.node_tree.nodes) > 0
        )
        if get_mixar_paint_preferences().skip_property_popups and not event.shift:
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        """Draw material creation dialog UI."""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        main_col = layout.column(align=False)

        # Warn before wiping the existing node tree (execute removes all nodes)
        if getattr(self, "_will_remove_nodes", False):
            warn_box = main_col.box()
            warn_col = warn_box.column(align=True)
            warn_col.alert = True
            warn_col.label(
                text="Existing material nodes will be removed.", icon="ERROR"
            )
            main_col.separator(factor=0.8)

        # Material Setup Section
        name_box = main_col.box()
        name_col = name_box.column(align=False)
        header_row = name_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Material Setup", icon="MATERIAL")
        name_col.separator(factor=1.2)

        name_row = name_col.row(align=True)
        name_row.scale_y = 1.4
        name_split = name_row.split(factor=0.15, align=True)
        label_col = name_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        name_split.prop(self, "tree_name", text="")
        name_col.separator(factor=0.4)

        mat_name_row = name_col.row(align=True)
        mat_name_row.scale_y = 1.2
        mat_name_split = mat_name_row.split(factor=0.15, align=True)
        mat_name_split.label(text="")
        checkbox_col = mat_name_split.column(align=True)
        checkbox_col.prop(
            self, "set_material_name_from_tree_name", text="Set material name to match"
        )
        name_col.separator(factor=0.7)

        type_row = name_col.row(align=True)
        type_row.scale_y = 1.4
        type_split = type_row.split(factor=0.15, align=True)
        label_col = type_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Type:")
        type_split.prop(self, "type", text="")
        name_col.separator(factor=0.8)
        main_col.separator(factor=0.8)

        # Channels Section
        if self.type != "EMISSION":
            channels_box = main_col.box()
            ch_col = channels_box.column(align=False)
            ch_header = ch_col.row(align=True)
            ch_header.scale_y = 1.4
            ch_header.label(text="Channels", icon="NODE")
            ch_col.separator(factor=1.2)

            ch_grid = ch_col.column(align=True)
            ch_row = ch_grid.row(align=True)
            ch_row.scale_y = 1.5
            ch_row.alignment = "EXPAND"
            ch_row.prop(self, "color", text="Color", toggle=True)
            ch_row.prop(self, "ao", text="AO", toggle=True)
            if self.type == "BSDF_PRINCIPLED":
                ch_row.prop(self, "metallic", text="Metal", toggle=True)
            ch_row.prop(self, "roughness", text="Rough", toggle=True)
            ch_row.prop(self, "normal", text="Normal", toggle=True)
            ch_col.separator(factor=0.8)
            main_col.separator(factor=1.2)

    def execute(self, context):
        """Create layer-based material system."""
        original_mode = context.mode
        obj = get_active_object()
        mat = get_active_material(obj)

        # Ensure object has a material
        if not mat:
            material_name = (
                self.tree_name if self.set_material_name_from_tree_name
                else f"{obj.name}_Material"
            )
            mat = bpy.data.materials.new(material_name)
            if len(obj.data.materials) == 0:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[obj.active_material_index] = mat

        mat = obj.active_material
        if not mat:
            material_name = (
                self.tree_name if self.set_material_name_from_tree_name else obj.name
            )
            mat = bpy.data.materials.new(material_name)
            if len(obj.material_slots) > 0:
                matslot = obj.material_slots[obj.active_material_index]
                matslot.material = mat
            else:
                obj.data.materials.append(mat)

        if self.set_material_name_from_tree_name:
            mat.name = self.tree_name

        if not mat.node_tree:
            mat.use_nodes = True

        # Remove all existing nodes
        if mat.node_tree:
            for n in list(mat.node_tree.nodes):
                mat.node_tree.nodes.remove(n)

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        ao_needed = self.ao and self.type != "EMISSION"

        main_bsdf = None
        outsoc = None
        ao_mul = None
        loc = Vector((0, 0))

        # Create group node
        group_tree = create_new_group_tree(mat, self.tree_name)
        node = nodes.new(type="ShaderNodeGroup")
        node.node_tree = group_tree
        node.select = True
        nodes.active = node
        mat.mp.active_mpaint_node = node.name

        # Create BSDF node
        if self.type == "BSDF_PRINCIPLED":
            main_bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            if "Subsurface Radius" in main_bsdf.inputs:
                main_bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.2, 0.1)
            if "Subsurface Color" in main_bsdf.inputs:
                main_bsdf.inputs["Subsurface Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        elif self.type == "BSDF_DIFFUSE":
            main_bsdf = nodes.new("ShaderNodeBsdfDiffuse")
        elif self.type == "EMISSION":
            main_bsdf = nodes.new("ShaderNodeEmission")

        # Position nodes
        node.location = loc.copy()
        loc.x += 200

        if ao_needed:
            ao_mul = simple_new_mix_node(mat.node_tree)
            ao_mixcol0, ao_mixcol1, ao_mixout = get_mix_color_indices(ao_mul)
            ao_mul.inputs[0].default_value = 1.0
            ao_mul.blend_type = "MULTIPLY"
            ao_mul.label = get_addon_title() + " AO Multiply"
            ao_mul.name = AO_MULTIPLY
            ao_mul.inputs[ao_mixcol0].default_value = (1.0, 1.0, 1.0, 1.0)
            ao_mul.inputs[ao_mixcol1].default_value = (1.0, 1.0, 1.0, 1.0)
            ao_mul.location = loc.copy()
            loc.x += 200

        main_bsdf.location = loc.copy()
        loc.x += 270 if main_bsdf.type == "BSDF_PRINCIPLED" else 200

        if not outsoc:
            mat_out = nodes.new(type="ShaderNodeOutputMaterial")
            mat_out.is_active_output = True
            outsoc = mat_out.inputs[0]
            mat_out.location = loc.copy()
            loc.x += 200

        links.new(main_bsdf.outputs[0], outsoc)

        # Add channels
        ch_color = ch_ao = ch_metallic = ch_roughness = ch_normal = None

        if self.color:
            ch_color = create_new_mp_channel(group_tree, "Color", "RGB", non_color=False)
        if self.type != "EMISSION":
            if self.ao:
                ch_ao = create_new_mp_channel(
                    group_tree, "Ambient Occlusion", "RGB", non_color=True
                )
            if self.type == "BSDF_PRINCIPLED" and self.metallic:
                ch_metallic = create_new_mp_channel(
                    group_tree, "Metallic", "VALUE", non_color=True
                )
            if self.roughness:
                ch_roughness = create_new_mp_channel(
                    group_tree, "Roughness", "VALUE", non_color=True
                )
            if self.normal:
                ch_normal = create_new_mp_channel(group_tree, "Normal", "NORMAL")

        check_all_channel_ios(group_tree.mp, mp_node=node)
        if self.use_linear_blending:
            group_tree.mp.use_linear_blending = self.use_linear_blending

        # Remap channel pointers
        ch_color = group_tree.mp.channels.get("Color")
        ch_ao = group_tree.mp.channels.get("Ambient Occlusion")
        ch_metallic = group_tree.mp.channels.get("Metallic")
        ch_roughness = group_tree.mp.channels.get("Roughness")
        ch_normal = group_tree.mp.channels.get("Normal")

        self._connect_channels(
            node, main_bsdf, ao_mul, links,
            ch_color, ch_ao, ch_metallic, ch_roughness, ch_normal
        )

        # Switch to Material Preview shading if not in texture paint mode
        if context.mode != 'PAINT_TEXTURE':
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces[0].shading.type = "MATERIAL"

        # Expand channels if only one mp node
        mp_nodes = [ng for ng in bpy.data.node_groups
                    if hasattr(ng, "mp") and ng.mp.is_mpaint_node]
        if len(mp_nodes) == 1:
            context.window_manager.mpui.expand_channels = True

        # Create default layer
        if self.create_default_layer:
            mp = group_tree.mp
            mp.halt_update = True
            try:
                bpy.ops.wm.m_new_layer(
                    'INVOKE_DEFAULT', type='COLOR', add_mask=False, default_layer=True
                )
                mp.active_layer_index = 0
            finally:
                mp.halt_update = False

            # Enable channels on fill layer based on created root channels
            if mp.layers:
                fill_layer = mp.layers[mp.active_layer_index]
                for i, ch in enumerate(fill_layer.channels):
                    if i < len(mp.channels):
                        # All created channels should be enabled on the fill layer
                        ch.enable = True

        request_ui_refresh()

        # Ensure the fresh group -> BSDF links take effect and the depsgraph
        # re-evaluates, so a scripted EXEC_DEFAULT create (agent path, no UI event
        # loop) renders the new material instead of a stale/foreign shader.
        commit_mp_material(node, mat, context)

        # Prompt to bake AO if AO channel was created
        ao_created = self.ao and self.type != "EMISSION"
        if ao_created:
            # Use timer to show prompt after current operator finishes
            def show_ao_prompt():
                bpy.ops.layers.ao_bake_prompt('INVOKE_DEFAULT')
                return None
            bpy.app.timers.register(show_ao_prompt, first_interval=0.1)

        # Restore original mode if needed
        if original_mode == 'PAINT_TEXTURE' and context.mode != 'PAINT_TEXTURE':
            try:
                bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
            except RuntimeError:
                pass

        return {"FINISHED"}

    def _connect_channels(self, node, main_bsdf, ao_mul, links,
                          ch_color, ch_ao, ch_metallic, ch_roughness, ch_normal):
        """Connect channel outputs to BSDF inputs."""
        if ch_color:
            inp = main_bsdf.inputs[0]
            for l in inp.links:
                links.new(l.from_socket, node.inputs[ch_color.name])
            set_input_default_value(node, ch_color, inp.default_value)
            if ch_ao and ao_mul:
                ao_mixcol0, ao_mixcol1, ao_mixout = get_mix_color_indices(ao_mul)
                links.new(node.outputs[ch_color.name], ao_mul.inputs[ao_mixcol0])
                links.new(node.outputs[ch_ao.name], ao_mul.inputs[ao_mixcol1])
                links.new(ao_mul.outputs[ao_mixout], inp)
            else:
                links.new(node.outputs[ch_color.name], inp)

        if ch_ao:
            set_input_default_value(node, ch_ao, (1.0, 1.0, 1.0, 1.0))

        if ch_metallic:
            inp = main_bsdf.inputs["Metallic"]
            for l in inp.links:
                links.new(l.from_socket, node.inputs[ch_metallic.name])
            set_input_default_value(node, ch_metallic, inp.default_value)
            links.new(node.outputs[ch_metallic.name], inp)

        if ch_roughness:
            inp = main_bsdf.inputs["Roughness"]
            for l in inp.links:
                links.new(l.from_socket, node.inputs[ch_roughness.name])
            set_input_default_value(node, ch_roughness, inp.default_value)
            links.new(node.outputs[ch_roughness.name], inp)

        if ch_normal:
            inp = main_bsdf.inputs["Normal"]
            for l in inp.links:
                links.new(l.from_socket, node.inputs[ch_normal.name])
            set_input_default_value(node, ch_normal)
            links.new(node.outputs[ch_normal.name], inp)


# Classes for registration
classes = (
    LAYERS_OT_AOBakePrompt,
    LAYERS_OT_CreateMaterial,
)
