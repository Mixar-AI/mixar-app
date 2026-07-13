# SPDX-FileCopyrightText: 2023 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

if(WITH_BLENDER)
  if(WITH_INPUT_NDOF)
    add_definitions(-DWITH_INPUT_NDOF)
  endif()

  add_subdirectory(animation)
  add_subdirectory(armature)
  add_subdirectory(asset)
  add_subdirectory(curve)
  add_subdirectory(curves)
  add_subdirectory(geometry)
  add_subdirectory(gizmo_library)
  add_subdirectory(gpencil_legacy)
  add_subdirectory(grease_pencil)
  add_subdirectory(id_management)
  add_subdirectory(interface)
  add_subdirectory(io)
  add_subdirectory(lattice)
  add_subdirectory(mask)
  add_subdirectory(mesh)
  add_subdirectory(metaball)
  add_subdirectory(object)
  add_subdirectory(physics)
  add_subdirectory(pointcloud)
  add_subdirectory(render)
  add_subdirectory(scene)
  add_subdirectory(sculpt_paint)
  add_subdirectory(sound)
  add_subdirectory(space_action)
  add_subdirectory(space_api)
  add_subdirectory(space_buttons)
  add_subdirectory(space_clip)
  add_subdirectory(space_console)
  add_subdirectory(space_file)
  add_subdirectory(space_graph)
  add_subdirectory(space_image)
  add_subdirectory(space_info)
  add_subdirectory(space_mixie)  # Add Mixie space
  add_subdirectory(space_mixar_layers)  # Add Mixar Layers space
  add_subdirectory(space_mixar_properties)  # Add Mixar Properties space
  add_subdirectory(space_mixar_assets)  # Add Mixar Assets space

  add_subdirectory(space_baking)  # Add Texturing Baking space
  add_subdirectory(space_texture_sets)  # Add Texture Sets space
  add_subdirectory(space_mixie_chat)  # Add Mixie Chat space
  add_subdirectory(space_agent_bubble)  # Add floating Agent Bubble space
  add_subdirectory(space_nla)
  add_subdirectory(space_node)
  add_subdirectory(space_outliner)
  add_subdirectory(space_script)
  add_subdirectory(space_sequencer)
  add_subdirectory(space_spreadsheet)
  add_subdirectory(space_statusbar)
  add_subdirectory(space_text)
  add_subdirectory(space_topbar)
  add_subdirectory(space_userpref)
  add_subdirectory(space_view3d)
  add_subdirectory(transform)
  add_subdirectory(undo)
  add_subdirectory(util)
  add_subdirectory(uvedit)
  add_subdirectory(screen)
endif()

add_subdirectory(datafiles)
