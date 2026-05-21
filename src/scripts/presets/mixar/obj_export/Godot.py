# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
gs = bpy.context.window_manager.mixar_export_obj

gs.global_scale = 1.0
gs.forward_axis = 'NEGATIVE_Z'
gs.up_axis = 'Y'
gs.apply_modifiers = True
gs.apply_transform = True
gs.export_uv = True
gs.export_normals = True
gs.export_materials = True
gs.export_pbr_extensions = True
gs.export_triangulated_mesh = False
