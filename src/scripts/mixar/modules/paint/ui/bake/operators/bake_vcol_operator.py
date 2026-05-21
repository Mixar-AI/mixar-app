# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color baking operations"""

from mixar.config.logging_config import get_logger

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty

from ....core.element.create_vcol import new_vertex_color
from ....core.element.get_elements import get_vcol_index
from ....core.element.update_vcol import move_vcol, set_active_vertex_color
from ....core.material.get_materials import get_all_materials_with_mp_nodes
from ....core.node.node_utils import get_active_mpaint_node, get_vertex_colors
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_operator_description,
    get_scene_objects,
    get_user_preferences,
    set_active_object,
)
from ..utils.bake_common import (
    BaseBakeOperator,
    bake_to_vcol,
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)

logger = get_logger(__name__)


class MBakeChannelToVcol(bpy.types.Operator, BaseBakeOperator):
    """Bake Channel to Vertex Color"""

    bl_idname = "wm.m_bake_channel_to_vcol"
    bl_label = "Bake channel to vertex color"
    bl_options = {"REGISTER", "UNDO"}

    all_materials: BoolProperty(
        name="Bake All Materials",
        description="Bake all materials with Mixar Paint nodes rather than just the active one",
        default=False,
    )

    vcol_name: StringProperty(
        name="Target Vertex Color Name",
        description="Target vertex color name, it will create one if it doesn't exist",
        default="",
    )

    add_emission: BoolProperty(
        name="Add Emission",
        description="Add the result with Emission Channel",
        default=False,
    )

    emission_multiplier: FloatProperty(
        name="Emission Multiplier",
        description="Emission multiplier so the emission can be more visible on the result",
        default=1.0,
        min=0.0,
    )

    force_first_index: BoolProperty(
        name="Force First Index",
        description="Force target vertex color to be first on the vertex colors list (useful for exporting)",
        default=True,
    )

    include_alpha: BoolProperty(
        name="Include Alpha",
        description="Bake channel alpha to result (need channel enable alpha)",
        default=False,
    )

    bake_to_alpha_only: BoolProperty(
        name="Bake To Alpha Only",
        description="Bake value into the alpha",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    @classmethod
    def description(self, context, properties):
        return get_operator_description(self)

    def invoke(self, context, event):
        self.invoke_operator(context)

        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        channel = mp.channels[mp.active_channel_index]

        self.vcol_name = "Baked " + channel.name

        # Add emission will only be available if it's on Color channel
        self.show_emission_option = False
        if channel.name == "Color":
            for ch in mp.channels:
                if ch.name == "Emission":
                    self.show_emission_option = True

        # Only the 'RGB' type has alpha data
        self.show_include_alpha_option = False
        if channel.type == "RGB":
            self.show_include_alpha_option = True

        # The type 'VALUE' can optionally be directly into the alpha channel
        self.show_bake_to_alpha_only_option = False
        if channel.type == "VALUE":
            self.show_bake_to_alpha_only_option = True

        if get_user_preferences().skip_property_popups and not event.shift:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== BAKE TO VERTEX COLOR ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Bake to Vertex Color", icon="VPAINT_HLT")

        col.separator(factor=1.2)

        # Target Vertex Color
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Target VCol:")
        split.prop(self, "vcol_name", text="")
        col.separator(factor=0.4)

        if self.show_emission_option:
            # Add Emission
            row = col.row(align=True)
            row.scale_y = 1.2
            split = row.split(factor=0.25, align=True)
            label_col = split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Add Emission:")
            split.prop(self, "add_emission", text="")
            col.separator(factor=0.4)

            # Emission Multiplier
            row = col.row(align=True)
            row.scale_y = 1.4
            split = row.split(factor=0.25, align=True)
            label_col = split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Multiplier:")
            split.prop(self, "emission_multiplier", text="")
            col.separator(factor=0.4)

        if self.show_include_alpha_option:
            # Include Alpha
            row = col.row(align=True)
            row.scale_y = 1.2
            split = row.split(factor=0.25, align=True)
            label_col = split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Include Alpha:")
            split.prop(self, "include_alpha", text="")
            col.separator(factor=0.4)

        if self.show_bake_to_alpha_only_option:
            # Bake to Alpha
            row = col.row(align=True)
            row.scale_y = 1.2
            split = row.split(factor=0.25, align=True)
            label_col = split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="To Alpha Only:")
            split.prop(self, "bake_to_alpha_only", text="")
            col.separator(factor=0.4)

        # Force First Index
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Force First:")
        split.prop(self, "force_first_index", text="")
        col.separator(factor=0.4)

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        mat = get_active_material()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        channel = mp.channels[mp.active_channel_index]
        channel_name = channel.name

        book = remember_before_bake(mp)

        if self.all_materials:
            mats = get_all_materials_with_mp_nodes()
        else:
            mats = [mat]

        for mat in mats:
            for node in mat.node_tree.nodes:
                if (
                    node.type != "GROUP"
                    or not node.node_tree
                    or not node.node_tree.mp.is_mpaint_node
                ):
                    continue
                tree = node.node_tree
                mp = tree.mp
                channel = mp.channels.get(channel_name)
                if not channel:
                    continue

                # Get all objects using material
                objs = []
                meshes = []
                for ob in get_scene_objects():
                    if ob.type != "MESH":
                        continue
                    if ob.hide_viewport:
                        continue
                    # if not in_renderable_layer_collection(ob): continue
                    if len(ob.data.polygons) == 0:
                        continue
                    for i, m in enumerate(ob.data.materials):
                        if m == mat:
                            ob.active_material_index = i
                            if ob not in objs and ob.data not in meshes:
                                objs.append(ob)
                                meshes.append(ob.data)

                if not objs:
                    continue

                set_active_object(objs[0])

                # Check vertex color
                for ob in objs:
                    vcols = get_vertex_colors(ob)
                    vcol = vcols.get(self.vcol_name)

                    # Set index to first so new vcol will copy their value
                    if len(vcols) > 0:
                        first_vcol = vcols[0]
                        set_active_vertex_color(ob, first_vcol)

                    if not vcol:
                        try:
                            vcol = new_vertex_color(ob, self.vcol_name)
                        except Exception as e:
                            logger.error("Error creating vertex color: %s", e)

                    # Get newly created vcol name
                    vcol_name = vcol.name

                    # NOTE: Because of api changes, vertex color shift doesn't work with Blender 3.2
                    if self.force_first_index:
                        move_vcol(ob, get_vcol_index(ob, vcol.name), 0)

                    # Get the newly created vcol to avoid pointer error
                    vcol = vcols.get(vcol_name)
                    set_active_vertex_color(ob, vcol)

                # Multi-material setup
                ori_mat_ids = {}
                for ob in objs:

                    # Need to assign all polygon to active material if there are multiple materials
                    ori_mat_ids[ob.name] = []

                    if len(ob.data.materials) > 1:

                        active_mat_id = [
                            i for i, m in enumerate(ob.data.materials) if m == mat
                        ][0]
                        for p in ob.data.polygons:

                            # Set active mat
                            ori_mat_ids[ob.name].append(p.material_index)
                            p.material_index = active_mat_id

                # Prepare bake settings
                prepare_bake_settings(
                    book,
                    objs,
                    mp,
                    disable_problematic_modifiers=True,
                    bake_device=self.bake_device,
                    bake_target="VERTEX_COLORS",
                )

                # Get extra channel
                extra_channel = None
                if self.show_emission_option and self.add_emission:
                    extra_channel = mp.channels.get("Emission")

                # Bake channel
                bake_to_vcol(
                    mat,
                    node,
                    channel,
                    objs,
                    extra_channel,
                    self.emission_multiplier,
                    self.include_alpha or self.bake_to_alpha_only,
                    self.vcol_name,
                )

                for ob in objs:
                    # Recover material index
                    if ori_mat_ids[ob.name]:
                        for i, p in enumerate(ob.data.polygons):
                            if ori_mat_ids[ob.name][i] != p.material_index:
                                p.material_index = ori_mat_ids[ob.name][i]

        # Recover bake settings
        recover_bake_settings(book, mp)

        return {"FINISHED"}


classes = (MBakeChannelToVcol,)
