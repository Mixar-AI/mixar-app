# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from . import utils
from . import core_td_operators, add_td_operators, viz_operators
from .constants import *


def panel_draw(layout, context):
	td = context.scene.td
	# Check if we're in VIEW_3D panel
	is_view_3d_panel = context.area and context.area.type == 'VIEW_3D'
	# Check if we're in Mixar UV panel (IMAGE_EDITOR sidebar in MIXAR_UV mode)
	is_mixar_uv_panel = (context.area and context.area.type == 'IMAGE_EDITOR'
	                     and context.space_data and context.space_data.mode == 'MIXAR_UV')

	if not (context.active_object and context.active_object.type == 'MESH'
	        and len(context.active_object.data.uv_layers) > 0):
		_draw_no_uv_message(layout, context)
		return

	# Mixar UV view uses its own Selection-style layout.
	if is_mixar_uv_panel:
		_draw_mixar_uv(layout, context, td)
	else:
		_draw_default(layout, context, td, is_view_3d_panel)


def _draw_no_uv_message(layout, context):
	if not context.active_object or context.active_object.type != 'MESH':
		box = layout.box()
		row = box.row(align=True)
		row.label(text="Active object isn't a mesh", icon='ERROR')
	elif context.active_object and len(context.active_object.data.uv_layers) == 0:
		box = layout.box()
		row = box.row(align=True)
		row.label(text="Mesh doesn't have any UV", icon='ERROR')


# =============================================================================
# Mixar UV view — Selection-style sub-section boxes (icon + title + content).
# =============================================================================

def _mixar_section(layout, title, icon='NONE'):
	"""Open a Selection-style sub-section box and return its content column."""
	box = layout.box()
	col = box.column(align=True)
	col.label(text=title, icon=icon)
	col.separator(factor=0.5)
	return col


# Width of the left label column inside Mixar UV sub-sections. Picked so
# property labels like "Set Method:" and "Scale Anchor:" fit comfortably
# while leaving most of the row to the input/dropdown control.
_MIXAR_LABEL_FACTOR = 0.4


def _labelled_prop(col, owner, prop_name, label, suffix=None):
	"""Draw a `label : control [suffix]` row aligned by a fixed split factor.

	The label sits in a fixed-width left column so labels of varying length
	(`Texel Density:`, `Method:`, `Scale Anchor:`) line up vertically with
	the controls below. When `suffix` is provided it's drawn as a label to
	the right of the control — used for unit hints like `px/cm`.
	"""
	split = col.split(factor=_MIXAR_LABEL_FACTOR, align=True)
	split.label(text=label)
	if suffix:
		right = split.row(align=True)
		right.prop(owner, prop_name, text="")
		right.label(text=suffix)
	else:
		split.prop(owner, prop_name, text="")


def _draw_mixar_uv(layout, context, td):
	layout.use_property_split = False
	layout.use_property_decorate = False
	layout.separator(factor=0.5)

	cur_units = TD_UNITS_ITEMS[int(td.units)][1]
	is_edit = context.object and context.object.mode == 'EDIT'

	# ---- Top controls (no box): Units + Texture Size + Selected Faces ----
	top = layout.column(align=True)
	row = top.row(align=True)
	row.label(text="Units:")
	row.prop(td, 'units', text="")
	row.label(text="Texture Size:")
	row.prop(td, 'texture_size', text="")
	if td.texture_size == 'CUSTOM':
		row = top.row(align=True)
		row.label(text="Width:")
		row.prop(td, "custom_width")
		row.label(text=" px")
		row = top.row(align=True)
		row.label(text="Height:")
		row.prop(td, "custom_height")
		row.label(text=" px")
	if is_edit:
		# Plain checkbox — matches the Unwrap panel's Fill Holes /
		# Correct Aspect style (no manual CHECKBOX_HLT/DEHLT icon).
		top.prop(td, "selected_faces", text="Selected Faces")

	layout.separator(factor=0.5)

	# ---- Calculate ----
	col = _mixar_section(layout, "Calculate", icon='DRIVER_DISTANCE')
	row = col.row(align=True)
	row.label(text="UV Space:")
	row.label(text=f"{td.uv_space} %")
	row = col.row(align=True)
	row.label(text="Density:")
	row.label(text=f"{td.density} {cur_units}")
	col.separator(factor=0.5)
	row = col.row(align=True)
	row.scale_y = 1.3
	row.operator(core_td_operators.TexelDensityCheck.bl_idname, icon='EXPORT')

	layout.separator(factor=0.5)

	# ---- Set Texel Density ----
	col = _mixar_section(layout, "Set Texel Density", icon='IMPORT')
	# Consistent label-column width so all three rows align. Unit (e.g.
	# "px/cm") is rendered as a trailing label on the right of the input.
	_labelled_prop(col, td, "density_set", "Texel Density:", suffix=cur_units)
	_labelled_prop(col, td, 'set_method', "Method:")
	_labelled_prop(col, td, 'rescale_anchor', "Scale Anchor:")
	col.separator(factor=0.5)
	row = col.row(align=True)
	row.scale_y = 1.3
	row.operator(core_td_operators.TexelDensitySet.bl_idname, icon='IMPORT')

	# ---- Selection by TD (EDIT only) ----
	if is_edit:
		layout.separator(factor=0.5)
		col = _mixar_section(layout, "Selection by Texel Density", icon='RESTRICT_SELECT_OFF')
		_labelled_prop(col, td, "select_mode", "Select:")
		_labelled_prop(col, td, "select_type", "Select Type:")
		if td.select_mode in ("FACES_BY_TD", "ISLANDS_BY_TD"):
			_labelled_prop(col, td, "select_value", "Texel Density:", suffix=cur_units)
		elif td.select_mode == "ISLANDS_BY_SPACE":
			_labelled_prop(col, td, "select_value", "UV Space:", suffix="%")
		else:
			_labelled_prop(col, td, "select_value", "Value:")
		if td.select_type == "EQUAL":
			_labelled_prop(col, td, "select_threshold", "Select Threshold:")
		col.separator(factor=0.5)
		row = col.row(align=True)
		row.scale_y = 1.3
		if td.select_mode == "FACES_BY_TD":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname,
			             text="Select Faces By TD", icon='ZOOM_SELECTED')
		elif td.select_mode == "ISLANDS_BY_TD":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname,
			             text="Select Islands By TD", icon='ZOOM_SELECTED')
		elif td.select_mode == "ISLANDS_BY_SPACE":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname,
			             text="Select Islands By UV Space", icon='ZOOM_SELECTED')


# =============================================================================
# Default (VIEW_3D and other) — original layout, untouched.
# =============================================================================

def _draw_default(layout, context, td, is_view_3d_panel):
	box = layout.box()
	row = box.row(align=True)
	row.label(text="Units:")
	row.prop(td, 'units', expand=False)
	row = box.row(align=True)
	row.label(text="Texture Size:")
	row.prop(td, 'texture_size', expand=False)

	if td.texture_size == 'CUSTOM':
		row = box.row(align=True)
		row.label(text="Width:")
		row.prop(td, "custom_width")
		row.label(text=" px")

		row = box.row(align=True)
		row.label(text="Height:")
		row.prop(td, "custom_height")
		row.label(text=" px")

	if is_view_3d_panel:
		box = layout.box()
		row = box.row(align=True)
		row.label(text="Checker Method:")
		row.prop(td, 'checker_method', expand=False)

		row = box.row(align=True)
		row.label(text="Checker Type:")
		row.prop(td, 'checker_type', expand=False)

		row = box.row(align=True)
		row.label(text="UV Scale:")
		row.prop(td, 'checker_uv_scale')

	if context.object and context.object.mode == 'EDIT':
		box = layout.box()
		row = box.row()
		if td.selected_faces:
			row.prop(td, "selected_faces", text="Selected Faces", icon="CHECKBOX_HLT")
		else:
			row.prop(td, "selected_faces", text="Selected Faces", icon="CHECKBOX_DEHLT")

	box = layout.box()
	row = box.row(align=True)
	row.label(text="UV Space:")
	row.label(text=f"{td.uv_space} %")

	cur_units = TD_UNITS_ITEMS[int(td.units)][1]

	row = box.row(align=True)
	row.label(text="Density:")
	row.label(text=f"{td.density} {cur_units}")

	row = box.row()
	row.operator(core_td_operators.TexelDensityCheck.bl_idname, icon='EXPORT')
	row = box.row()
	row.operator(add_td_operators.CalculatedToSet.bl_idname, icon='COPYDOWN')
	if context.object and context.object.mode == 'EDIT':
		row = box.row()
		row.operator(add_td_operators.CalculatedToSelect.bl_idname, icon='COPYDOWN')

	box = layout.box()
	row = box.row(align=True)
	row.label(text="Set TD:")
	row.prop(td, "density_set")
	row.label(text=f" {cur_units}")

	row = box.row(align=True)
	row.label(text="Set Method:")
	row.prop(td, 'set_method', expand=False)

	row = box.row(align=True)
	row.label(text="Scale Anchor:")
	row.prop(td, 'rescale_anchor', expand=False)

	row = box.row()
	row.operator(core_td_operators.TexelDensitySet.bl_idname, icon='IMPORT')

	box = layout.box()

	# Preset Buttons
	preset_rows = TD_PRESET_VALUES.get(td.units)
	if preset_rows:
		for preset_row in preset_rows:
			row = box.row(align=True)
			for val in preset_row:
				op = row.operator(add_td_operators.PresetSet.bl_idname, text=val)
				op.td_value = val

	row = box.row(align=True)
	row.operator(add_td_operators.PresetSet.bl_idname, text="Half TD", icon='FULLSCREEN_EXIT').td_value = "Half"
	row.operator(add_td_operators.PresetSet.bl_idname, text="Double TD", icon='FULLSCREEN_ENTER').td_value = "Double"

	if context.object and context.object.mode == 'OBJECT':
		row = layout.row()
		row.operator(add_td_operators.TexelDensityCopy.bl_idname, icon='UV_SYNC_SELECT')

	if context.object and context.object.mode == 'EDIT':
		box = layout.box()
		row = box.row(align=True)
		row.label(text="Select:")
		row.prop(td, "select_mode", expand=False)

		row = box.row(align=True)
		row.label(text="Select Type:")
		row.prop(td, "select_type", expand=False)

		row = box.row(align=True)
		if td.select_mode == "FACES_BY_TD" or td.select_mode == "ISLANDS_BY_TD":
			row.label(text="Texel:")
		elif td.select_mode == "ISLANDS_BY_SPACE":
			row.label(text="UV Space:")

		row.prop(td, "select_value")

		if td.select_mode == "FACES_BY_TD" or td.select_mode == "ISLANDS_BY_TD":
			row.label(text=" " + cur_units)
		elif td.select_mode == "ISLANDS_BY_SPACE":
			row.label(text=" %")

		if td.select_type == "EQUAL":
			row = box.row(align=True)
			row.label(text="Select Threshold:")
			row.prop(td, "select_threshold")

		row = box.row()
		if td.select_mode == "FACES_BY_TD":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname, text="Select Faces By TD", icon='ZOOM_SELECTED')
		elif td.select_mode == "ISLANDS_BY_TD":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname, text="Select Islands By TD", icon='ZOOM_SELECTED')
		elif td.select_mode == "ISLANDS_BY_SPACE":
			row.operator(add_td_operators.SelectByTDOrUVSpace.bl_idname, text="Select Islands By UV Space", icon='ZOOM_SELECTED')

	if is_view_3d_panel:
		box = layout.box()
		row = box.row(align=True)
		row.label(text="Bake VC Mode:")
		row.prop(td, "bake_vc_mode", expand=False)

		if td.bake_vc_mode in {"TD_FACES_TO_VC", "TD_ISLANDS_TO_VC"}:
			row = box.row()
			if td.bake_vc_auto_min_max:
				row.prop(td, "bake_vc_auto_min_max", text="Auto Min/Max Value", icon="CHECKBOX_HLT")
			else:
				row.prop(td, "bake_vc_auto_min_max", text="Auto Min/Max Value", icon="CHECKBOX_DEHLT")

			row = box.row(align=True)
			row.label(text="Min TD Value:")
			row.label(text="Max TD Value:")

			if td.bake_vc_auto_min_max:
				row = box.row(align=True)
				row.label(text=f"  {td.bake_vc_min_td}")
				row.label(text=f"  {td.bake_vc_max_td}")
			else:
				row = box.row(align=True)
				row.prop(td, "bake_vc_min_td")
				row.prop(td, "bake_vc_max_td")

		if td.bake_vc_mode == "UV_SPACE_TO_VC":
			row = box.row(align=True)
			row.label(text="Min UV Space:")
			row.label(text="Max UV Space:")

			row = box.row(align=True)
			row.prop(td, "bake_vc_min_space")
			row.prop(td, "bake_vc_max_space")

		if td.bake_vc_mode == "UV_ISLANDS_TO_VC":
			row = box.row(align=True)
			row.label(text="Island Detect Mode:")
			row.prop(td, "uv_islands_to_vc_mode", expand=False)

		if td.bake_vc_mode == 'DISTORTION':
			row = box.row(align=True)
			row.label(text="Range:")
			row.prop(td, "bake_vc_distortion_range")
			row.label(text=" %")

		if td.bake_vc_mode in {"TD_FACES_TO_VC", "TD_ISLANDS_TO_VC", "UV_SPACE_TO_VC", 'DISTORTION'}:
			row = box.row()
			if td.bake_vc_show_gradient:
				row.prop(td, "bake_vc_show_gradient", text="Show Gradient", icon="CHECKBOX_HLT")
			else:
				row.prop(td, "bake_vc_show_gradient", text="Show Gradient", icon="CHECKBOX_DEHLT")

		if td.bake_vc_mode in {"TD_FACES_TO_VC", "TD_ISLANDS_TO_VC"}:
			row = box.row()
			row.operator(viz_operators.BakeTDToVC.bl_idname, text="Texel Density to VC", icon='RESTRICT_RENDER_OFF')

		if td.bake_vc_mode == "UV_SPACE_TO_VC":
			row = box.row()
			row.operator(viz_operators.BakeTDToVC.bl_idname, text="UV Space to VC", icon='RESTRICT_RENDER_OFF')

		if td.bake_vc_mode == "UV_ISLANDS_TO_VC":
			row = box.row()
			row.operator(viz_operators.BakeTDToVC.bl_idname, text="UV Islands to VC", icon='RESTRICT_RENDER_OFF')

		if td.bake_vc_mode == 'DISTORTION':
			row = box.row()
			row.operator(viz_operators.BakeTDToVC.bl_idname, text="UV Distortion to VC", icon='RESTRICT_RENDER_OFF')

		row = box.row()
		row.operator(viz_operators.ClearTDFromVC.bl_idname)


# Panel in 3D View
class TDAddonView3DPanel(bpy.types.Panel):
	bl_idname = "VIEW3D_PT_texel_density_checker"
	bl_label = "Texel Density Checker 2025.1"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_category = "Texel Density"

	@classmethod
	def poll(cls, context):
		# preferences = utils.get_preferences()
		# return (context.object is not None) and (context.active_object is not None) and preferences.view3d_panel_category_enable
		return True

	def draw(self, context):
		panel_draw(self.layout, context)




class IMAGE_PT_texel_density(bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Texel Density"
    bl_ui_units_x = 14

    def draw(self, context):
        pass


# Panel in UV Editor
class TDAddonUVPanel(bpy.types.Panel):
	# bl_idname = "UV_PT_texel_density_checker"
	bl_label = "Texel Density"
	bl_space_type = "IMAGE_EDITOR"
	bl_region_type = "HEADER"
	bl_parent_id = "IMAGE_PT_texel_density"

	@classmethod
	def poll(cls, context):
		sima = context.space_data
		obj = context.active_object
		return (sima.show_uvedit and
                obj and
                obj.type == 'MESH' and
                obj.data)

	def draw(self, context):
		panel_draw(self.layout, context)



classes = (
	# TDAddonView3DPanel and TDAddonUVPanel are registered in texel_main.py
)
