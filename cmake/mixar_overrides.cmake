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
  include("${CMAKE_CURRENT_LIST_DIR}/windows_python_cache.cmake")
  set(CMAKE_CXX_FLAGS "/DWIN32 /D_WINDOWS /W3 /GR /EHsc" CACHE STRING "C++ compiler flags" FORCE)
  set(CMAKE_C_FLAGS "/DWIN32 /D_WINDOWS /W3" CACHE STRING "C compiler flags" FORCE)
endif()

# NVIDIA GPU rendering for Cycles, controlled from .env (see .env.example).
#
#   MIXAR_CUDA=0           no CUDA, no OptiX, no cubins at all
#   MIXAR_CUDA_BINARIES=0  keep CUDA/OptiX device support, skip the cubins
#   MIXAR_CUDA_ARCH=sm_89  narrow CYCLES_CUDA_BINARIES_ARCH to your own card
#   MIXAR_CUDA_BUILD_SERIAL=1 build cubins one at a time to cap peak RAM
#
# WITH_CYCLES_CUDA_BINARIES is the expensive one: it compiles the WHOLE Cycles
# kernel with nvcc once per architecture in CYCLES_CUDA_BINARIES_ARCH (ten
# passes by default), which dominates a from-scratch build. Upstream defaults
# it OFF for exactly that reason; Mixar ships it ON, so turning it off is a
# local-dev choice, never a release one.
#
# This file is the ONE place that decides. The Windows build script re-reads the
# same variables only to invalidate a cache configured with a different answer
# (it skips configure when build files already exist).
macro(mixar_env_bool _var _default _out)
  set(_mixar_val "$ENV{${_var}}")
  # settings.bat's .env reader keeps everything after the "=", so a trailing
  # "MIXAR_CUDA=0  # comment" arrives with the comment attached and would read
  # as ON - an hour of cubins for a setting you thought you turned off.
  string(REGEX REPLACE "#.*$" "" _mixar_val "${_mixar_val}")
  string(STRIP "${_mixar_val}" _mixar_val)
  if(_mixar_val STREQUAL "")
    set(_mixar_val "${_default}")
  endif()
  string(TOUPPER "${_mixar_val}" _mixar_val)
  if(_mixar_val MATCHES "^(0|OFF|NO|N|FALSE)$")
    set(${_out} OFF)
  else()
    set(${_out} ON)
  endif()
endmacro()

mixar_env_bool(MIXAR_CUDA ON MIXAR_CUDA_ENABLED)
mixar_env_bool(MIXAR_CUDA_BINARIES ${MIXAR_CUDA_ENABLED} MIXAR_CUDA_BINARIES_ENABLED)
mixar_env_bool(MIXAR_CUDA_BUILD_SERIAL OFF MIXAR_CUDA_BUILD_SERIAL_ENABLED)
if(NOT MIXAR_CUDA_ENABLED)
  set(MIXAR_CUDA_BINARIES_ENABLED OFF)
endif()

set(WITH_CYCLES_DEVICE_CUDA ${MIXAR_CUDA_ENABLED} CACHE BOOL "Enable Cycles NVIDIA CUDA compute support" FORCE)
set(WITH_CYCLES_CUDA_BINARIES ${MIXAR_CUDA_BINARIES_ENABLED} CACHE BOOL "Build Cycles NVIDIA CUDA binaries" FORCE)
set(WITH_CYCLES_CUDA_BUILD_SERIAL ${MIXAR_CUDA_BUILD_SERIAL_ENABLED} CACHE BOOL "Build Cycles CUDA binaries serially" FORCE)
set(WITH_CUDA_DYNLOAD ON CACHE BOOL "Dynamically load CUDA libraries at runtime" FORCE)

if(NOT "$ENV{CUDA_TOOLKIT_ROOT_DIR}" STREQUAL "")
  set(CUDA_TOOLKIT_ROOT_DIR "$ENV{CUDA_TOOLKIT_ROOT_DIR}" CACHE PATH "CUDA toolkit root" FORCE)
endif()

# OptiX rides with CUDA (requires the NVIDIA OptiX SDK).
set(WITH_CYCLES_DEVICE_OPTIX ${MIXAR_CUDA_ENABLED} CACHE BOOL "Enable Cycles NVIDIA OptiX support" FORCE)

if(MIXAR_CUDA_BINARIES_ENABLED AND NOT "$ENV{MIXAR_CUDA_ARCH}" STREQUAL "")
  string(REGEX REPLACE "#.*$" "" _mixar_cuda_arch "$ENV{MIXAR_CUDA_ARCH}")
  string(REPLACE "," ";" _mixar_cuda_arch "${_mixar_cuda_arch}")
  string(REPLACE " " ";" _mixar_cuda_arch "${_mixar_cuda_arch}")
  list(REMOVE_ITEM _mixar_cuda_arch "")
  set(CYCLES_CUDA_BINARIES_ARCH ${_mixar_cuda_arch} CACHE STRING "CUDA architectures to build binaries for" FORCE)
  message(STATUS "Mixar: CUDA binaries limited to ${_mixar_cuda_arch}")
endif()

if(MIXAR_CUDA_ENABLED)
  message(STATUS "Mixar: CUDA/OptiX ON (cubins: ${MIXAR_CUDA_BINARIES_ENABLED}, serial: ${MIXAR_CUDA_BUILD_SERIAL_ENABLED})")
else()
  message(STATUS "Mixar: CUDA/OptiX OFF (MIXAR_CUDA=$ENV{MIXAR_CUDA})")
endif()

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

# Release debug information for crash symbolication, set by the release
# pipeline (MIXAR_DEBUG_SYMBOLS=1 in .github/workflows/release.yml; local
# builds leave it off and build exactly as before).
#
#   macOS / Linux  -g1: function names, line tables and inlining only (clang
#                  reads it as -gline-tables-only). Code generation does not
#                  change. The CI turns the debug info into a dSYM / .debug file
#                  and the shipped binary is stripped as before (package.sh
#                  strips the debug map too, so it does not grow).
#   Windows        WITH_WINDOWS_RELEASE_PDB is passed by build.bat; the PDB
#                  stays out of the install (MIXAR_INSTALL_RELEASE_PDB).
#
# The base CMAKE_<LANG>_FLAGS are used because the platform files overwrite
# CMAKE_<LANG>_FLAGS_RELEASE after this preload runs.
mixar_env_bool(MIXAR_DEBUG_SYMBOLS OFF MIXAR_DEBUG_SYMBOLS_ENABLED)
if(MIXAR_DEBUG_SYMBOLS_ENABLED AND NOT CMAKE_HOST_WIN32)
  set(CMAKE_C_FLAGS "-g1" CACHE STRING "C compiler flags" FORCE)
  set(CMAKE_CXX_FLAGS "-g1" CACHE STRING "C++ compiler flags" FORCE)
  if(NOT CMAKE_HOST_APPLE)
    # Symbols are filed by GNU build-id; make sure the linker writes one.
    set(CMAKE_EXE_LINKER_FLAGS "-Wl,--build-id=sha1" CACHE STRING "Linker flags" FORCE)
    set(CMAKE_SHARED_LINKER_FLAGS "-Wl,--build-id=sha1" CACHE STRING "Linker flags" FORCE)
  endif()
  message(STATUS "Mixar: release debug information ON (-g1) for crash symbolication")
elseif(NOT CMAKE_HOST_WIN32 AND "${CMAKE_CXX_FLAGS}" STREQUAL "-g1")
  # A build directory configured by a release build: drop what it cached.
  set(CMAKE_C_FLAGS "" CACHE STRING "C compiler flags" FORCE)
  set(CMAKE_CXX_FLAGS "" CACHE STRING "C++ compiler flags" FORCE)
  set(CMAKE_EXE_LINKER_FLAGS "" CACHE STRING "Linker flags" FORCE)
  set(CMAKE_SHARED_LINKER_FLAGS "" CACHE STRING "Linker flags" FORCE)
endif()
