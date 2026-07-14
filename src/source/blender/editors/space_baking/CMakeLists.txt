# SPDX-FileCopyrightText: 2025 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set(INC
  ../include
  ../../makesrna
  ../../imbuf
  ${CMAKE_BINARY_DIR}/source/blender/makesrna
)

set(INC_SYS)

set(SRC
  space_baking.cc
  baking_ops_pixels.cc
  baking_ops_colorspace.cc
  baking_ops_alpha.cc
  baking_ops_filters.cc
  baking_ops_morphology.cc
  baking_ops_statistics.cc
  baking_ops_normal.cc
  baking_ops_blend.cc

  baking_intern.hh
  baking_ops_common.hh
)

set(LIB
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::blenloader
  PRIVATE bf::dna
  PRIVATE bf::imbuf
  PRIVATE bf::intern::clog
  PRIVATE bf::intern::guardedalloc
  PRIVATE bf::windowmanager
  bf_editor_interface
)

if(WITH_OPENMP)
  list(APPEND LIB PRIVATE OpenMP::OpenMP_CXX)
  add_definitions(-D_OPENMP)
endif()

blender_add_lib(bf_editor_space_baking "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")
add_dependencies(bf_editor_space_baking bf_rna)
