# SPDX-FileCopyrightText: 2025 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set(INC
  ../include
  ../../makesrna
  ${CMAKE_BINARY_DIR}/source/blender/makesrna
)

set(INC_SYS)

set(SRC
  space_mixar_layers.cc
)

set(LIB
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::blenloader
  PRIVATE bf::dna
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::windowmanager
  bf_editor_interface
)

blender_add_lib(bf_editor_space_mixar_layers "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")
add_dependencies(bf_editor_space_mixar_layers bf_rna)
