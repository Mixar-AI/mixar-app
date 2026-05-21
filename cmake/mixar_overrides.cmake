# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

# This file is loaded *before* any project() call
# You can override ANY cache variable in Blender.

# Only set CMP0167 policy if it's available (CMake 3.30+)
if(POLICY CMP0167)
  cmake_policy(SET CMP0167 OLD)
endif()

# Windows/MSVC: Base compiler flags.
if(CMAKE_HOST_WIN32)
  set(CMAKE_CXX_FLAGS "/DWIN32 /D_WINDOWS /W3 /GR /EHsc" CACHE STRING "C++ compiler flags" FORCE)
  set(CMAKE_C_FLAGS "/DWIN32 /D_WINDOWS /W3" CACHE STRING "C compiler flags" FORCE)
endif()

# Enable CUDA support for Cycles rendering
set(WITH_CYCLES_DEVICE_CUDA ON CACHE BOOL "Enable Cycles NVIDIA CUDA compute support" FORCE)
set(WITH_CYCLES_CUDA_BINARIES ON CACHE BOOL "Build Cycles NVIDIA CUDA binaries" FORCE)
set(WITH_CUDA_DYNLOAD ON CACHE BOOL "Dynamically load CUDA libraries at runtime" FORCE)

# Enable OptiX support for Cycles ray-tracing (requires NVIDIA OptiX SDK)
set(WITH_CYCLES_DEVICE_OPTIX ON CACHE BOOL "Enable Cycles NVIDIA OptiX support" FORCE)

# sccache compiler launcher - auto-enabled when sccache is on PATH.
# On Windows, Blender's platform_win32.cmake handles /Z7 and compiler launcher
# when WITH_WINDOWS_SCCACHE is ON. On other platforms, we set the launcher directly.
find_program(SCCACHE_PROGRAM sccache)
if(SCCACHE_PROGRAM)
  message(STATUS "sccache found: ${SCCACHE_PROGRAM}")
  if(CMAKE_HOST_WIN32)
    # Use Blender's native sccache support (handles /Z7, compiler launcher, PDB)
    set(WITH_WINDOWS_SCCACHE ON CACHE BOOL "" FORCE)
  else()
    set(CMAKE_C_COMPILER_LAUNCHER   "${SCCACHE_PROGRAM}" CACHE STRING "" FORCE)
    set(CMAKE_CXX_COMPILER_LAUNCHER "${SCCACHE_PROGRAM}" CACHE STRING "" FORCE)
  endif()
else()
  message(STATUS "sccache not found - building without compiler cache")
endif()
