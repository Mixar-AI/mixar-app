# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

# The MSI's custom-action DLL (#2079), added by
# build_files/cmake/packaging.cmake. It runs inside Windows Installer before
# Mixar or its runtime exists, so it links the C runtime statically: Blender
# builds everything with /MD, which this directory drops for this target alone.

foreach(_config "" _DEBUG _RELEASE _MINSIZEREL _RELWITHDEBINFO)
  string(REGEX REPLACE "/MDd?( |$)" "" CMAKE_C_FLAGS${_config} "${CMAKE_C_FLAGS${_config}}")
endforeach()
unset(_config)

add_library(mixar_msi_ca SHARED
  mixar_msi_ca.c
  mixar_msi_facts.c
  mixar_msi_scope.c
  mixar_msi_ca.h
  mixar_msi_scope.h
  mixar_msi_ca.def
)
target_link_libraries(mixar_msi_ca PRIVATE msi advapi32 wtsapi32 shell32 user32)
set_target_properties(mixar_msi_ca PROPERTIES
  MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
  # $<0:> keeps multi-config generators from adding a per-configuration
  # folder: the generated mixar_msi_ca.wxs names this exact path.
  RUNTIME_OUTPUT_DIRECTORY "${MIXAR_MSI_CA_DIR}$<0:>"
  LIBRARY_OUTPUT_DIRECTORY "${MIXAR_MSI_CA_DIR}$<0:>"
  ARCHIVE_OUTPUT_DIRECTORY "${MIXAR_MSI_CA_DIR}$<0:>"
)
