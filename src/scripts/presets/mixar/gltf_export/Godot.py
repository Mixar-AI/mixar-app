# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
gs = bpy.context.window_manager.mixar_export_gltf

gs.export_format = 'GLB'
gs.export_yup = True
gs.export_apply = True
gs.export_texcoords = True
gs.export_normals = True
gs.export_materials = 'EXPORT'
gs.export_image_format = 'AUTO'
gs.export_draco_mesh_compression_enable = False
gs.export_animations = True
