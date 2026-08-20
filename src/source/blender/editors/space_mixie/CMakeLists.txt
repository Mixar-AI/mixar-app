# SPDX-FileCopyrightText: 2025 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set(INC
  ../include
  ../../makesrna

  # RNA_prototypes.hh
  ${CMAKE_BINARY_DIR}/source/blender/makesrna
)

set(INC_SYS
)

set(SRC
  mixie_dragdrop.cc
  mixie_draw_moodboard.cc
  mixie_draw_moodboard_annotations.cc
  mixie_draw_moodboard_groups.cc
  mixie_draw_moodboard_graph.cc
  mixie_moodboard_graph_geometry.cc
  mixie_draw_moodboard_node_ui.cc
  mixie_draw_moodboard_images.cc
  mixie_draw_moodboard_textboxes.cc
  mixie_draw_moodboard_tools.cc
  mixie_draw_sam3d.cc
  mixie_header.cc
  mixie_moodboard_ops_box_select.cc
  mixie_moodboard_ops_crop.cc
  mixie_moodboard_ops_drop.cc
  mixie_moodboard_ops_graph.cc
  mixie_moodboard_ops_masks.cc
  mixie_moodboard_ops_preview.cc
  mixie_moodboard_ops_select.cc
  mixie_moodboard_ops_zoom.cc
  mixie_ops.cc
  mixie_select.cc
  space_mixie.cc

  mixie_draw_moodboard_intern.hh
  mixie_intern.hh
  mixie_moodboard_ops_common.hh
)

set(LIB
  PRIVATE bf::blenfont
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::blenloader
  PRIVATE bf::blentranslation
  PRIVATE bf::depsgraph
  PRIVATE bf::dna
  PRIVATE bf::gpu
  PRIVATE bf::imbuf
  PRIVATE bf::imbuf::movie
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::dependencies::fmt
  PRIVATE bf::windowmanager
  bf_editor_interface
)


blender_add_lib(bf_editor_space_mixie "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# RNA_prototypes.hh dna_type_offsets.h
add_dependencies(bf_editor_space_mixie bf_rna)
