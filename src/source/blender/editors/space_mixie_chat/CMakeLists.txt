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
  mixie_chat_agent_bubble.cc
  mixie_chat_dragdrop.cc
  mixie_chat_footer.cc
  mixie_chat_footer_cache.cc
  mixie_chat_footer_draw.cc
  mixie_chat_footer_layout.cc
  mixie_chat_footer_thumbnails.cc
  mixie_chat_header.cc
  mixie_chat_hit_testing.cc
  mixie_chat_main_region.cc
  mixie_chat_markdown.cc
  mixie_chat_markdown_parse.cc
  mixie_chat_mention.cc
  mixie_chat_table.cc
  mixie_chat_empty_state.cc
  mixie_chat_messages.cc
  mixie_chat_messages_content.cc
  mixie_chat_messages_layout.cc
  mixie_chat_messages_render.cc
  mixie_chat_props.cc
  mixie_chat_scroll_indicator.cc
  mixie_chat_selection.cc
  mixie_chat_slots.cc
  mixie_chat_steps.cc
  mixie_chat_thinking.cc
  mixie_chat_ui_primitives.cc
  mixie_chat_ui_theme.cc
  mixie_chat_ui_widgets.cc
  space_mixie_chat.cc

  mixie_chat_footer_constants.hh
  mixie_chat_footer_intern.hh
  mixie_chat_intern.hh
  mixie_chat_layout_data.hh
  mixie_chat_markdown_intern.hh
  mixie_chat_ui_types.hh
)

set(LIB
  PRIVATE bf::blenfont
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::blenloader
  PRIVATE bf::blentranslation
  PRIVATE bf::dna
  PRIVATE bf::gpu
  PRIVATE bf::imbuf
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::windowmanager
  bf_editor_interface
)

blender_add_lib(bf_editor_space_mixie_chat "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# RNA_prototypes.hh dna_type_offsets.h
add_dependencies(bf_editor_space_mixie_chat bf_rna)
