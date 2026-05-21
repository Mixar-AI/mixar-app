# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
gs = bpy.context.window_manager.mixar_export_fbx

gs.global_scale = 1.0
gs.apply_scale_options = 'FBX_SCALE_ALL'
gs.axis_forward = '-Z'
gs.axis_up = 'Y'
gs.apply_unit_scale = True
gs.use_space_transform = True
gs.bake_space_transform = False
gs.mesh_smooth_type = 'FACE'
gs.use_mesh_modifiers = True
gs.use_triangles = False
