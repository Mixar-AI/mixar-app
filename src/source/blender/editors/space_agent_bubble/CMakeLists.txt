# SPDX-FileCopyrightText: 2026 Mixar Authors
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
  space_agent_bubble.cc
  agent_ui_draw.cc
  agent_ui_icons.cc
  agent_ui_layout.cc
  agent_ui_queue.cc
  agent_ui_state.cc

  agent_bubble_intern.hh
  agent_ui_draw.hh
  agent_ui_icons.hh
  agent_ui_layout.hh
  agent_ui_queue.hh
  agent_ui_theme.hh
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
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::extern::fmtlib
  PRIVATE bf::windowmanager
  bf_editor_interface
  # We reuse mixie chat's custom-drawn footer region for our composer
  # so the agent bubble's input/composer looks and behaves identically
  # (auto-grow on Shift+Enter, attachment thumbnails, send button, …).
  bf_editor_space_mixie_chat
)

blender_add_lib(bf_editor_space_agent_bubble "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# RNA_prototypes.hh
add_dependencies(bf_editor_space_agent_bubble bf_rna)
