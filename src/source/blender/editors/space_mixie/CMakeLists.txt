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
  mixie_attachment_flight.cc
  mixie_attachment_geometry.cc
  mixie_attachment_geometry.hh
  mixie_attachment_motion.hh
  mixie_dragdrop.cc
  mixie_draw_moodboard.cc
  mixie_draw_moodboard_chrome.cc
  mixie_draw_moodboard_annotations.cc
  mixie_draw_moodboard_frames.cc
  mixie_draw_moodboard_frame_actions.cc
  mixie_draw_moodboard_graph.cc
  mixie_draw_moodboard_graph_chrome.cc
  mixie_draw_moodboard_graph_sockets.cc
  mixie_draw_moodboard_media_actions.cc
  mixie_draw_moodboard_media_labels.cc
  mixie_moodboard_graph_geometry.cc
  mixie_moodboard_graph_link_drag.cc
  mixie_moodboard_graph_hit.cc
  mixie_draw_moodboard_node_ui.cc
  mixie_draw_moodboard_node_settings.cc
  mixie_draw_moodboard_node_tile_controls.cc
  mixie_draw_moodboard_node_tooltips.cc
  mixie_moodboard_node_layout.cc
  mixie_moodboard_template_drag.cc
  mixie_moodboard_template_drag.hh
  mixie_draw_moodboard_images.cc
  mixie_draw_moodboard_texture_cache.cc
  mixie_draw_moodboard_textboxes.cc
  mixie_draw_moodboard_tools.cc
  mixie_draw_sam3d.cc
  mixie_header.cc
  mixie_moodboard_frame_geometry.cc
  mixie_moodboard_move_selection.cc
  mixie_moodboard_ops_box_select.cc
  mixie_moodboard_ops_crop.cc
  mixie_moodboard_ops_drop.cc
  mixie_moodboard_ops_graph.cc
  mixie_moodboard_ops_graph_context.cc
  mixie_moodboard_ops_graph_link.cc
  mixie_moodboard_ops_graph_resize.cc
  mixie_moodboard_ops_graph_selection.cc
  mixie_moodboard_ops_graph_video.cc
  mixie_moodboard_ops_masks.cc
  mixie_moodboard_ops_preview.cc
  mixie_moodboard_ops_preview_window.cc
  mixie_moodboard_ops_frame_select.cc
  mixie_moodboard_ops_rename_frame.cc
  mixie_moodboard_ops_rename_media.cc
  mixie_moodboard_ops_select.cc
  mixie_moodboard_ops_zoom.cc
  mixie_moodboard_resize_handles.cc
  mixie_ops.cc
  mixie_moodboard_qa_targets.cc
  mixie_select.cc
  space_mixie.cc

  mixie_draw_moodboard_intern.hh
  mixie_intern.hh
  mixie_moodboard_canvas.hh
  mixie_moodboard_chrome.hh
  mixie_moodboard_graph_geometry.hh
  mixie_moodboard_hit_geometry.hh
  mixie_moodboard_node_layout.hh
  mixie_moodboard_socket_style.hh
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
