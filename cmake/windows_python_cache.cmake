# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

# Run before project(): Blender checks the cached version before rediscovering
# Windows libraries. Preserve object files and unrelated configuration, but
# also clear dependency caches whose names do not start with PYTHON_.
function(mixar_clear_stale_python_cache expected_version)
  if(expected_version STREQUAL "" OR NOT DEFINED PYTHON_VERSION
      OR PYTHON_VERSION STREQUAL expected_version)
    return()
  endif()

  set(old_version "${PYTHON_VERSION}")
  string(REPLACE "." "\\." old_pattern "${old_version}")
  string(REPLACE "." "" old_digits "${old_version}")
  set(python_path "[Pp][Yy][Tt][Hh][Oo][Nn](-?${old_pattern}|[/\\\\]${old_digits}([/\\\\]|$)|${old_digits}(_d)?\\.(lib|dll))")
  get_cmake_property(cache_variables CACHE_VARIABLES)
  set(cleared 0)
  foreach(variable IN LISTS cache_variables)
    if(variable MATCHES "^PYTHON_" OR "${${variable}}" MATCHES "${python_path}")
      unset("${variable}" CACHE)
      math(EXPR cleared "${cleared} + 1")
    endif()
  endforeach()
  message(STATUS "Cleared ${cleared} cached Python ${old_version} entries; rediscovering Python ${expected_version}")
endfunction()

mixar_clear_stale_python_cache("$ENV{PYTHON_VERSION}")

# A Blender release renames versioned libraries (5.2 ships dpcpp `sycl8.lib`, 5.3
# `sycl9.lib`). find_library() results are cached, so a build directory shared
# across releases kept the old file name and Ninja stopped with "missing and no
# known rule to make it". Forget every cached path into the pinned Windows
# library tree that no longer exists; CMake then finds the current file. Paths
# outside that tree, empty values and NOTFOUND results are left alone.
function(mixar_clear_missing_library_cache)
  get_cmake_property(cache_variables CACHE_VARIABLES)
  set(cleared 0)
  foreach(variable IN LISTS cache_variables)
    get_property(variable_type CACHE "${variable}" PROPERTY TYPE)
    if(NOT variable_type MATCHES "^(FILEPATH|PATH)$")
      continue()
    endif()
    set(value "${${variable}}")
    if(value STREQUAL "" OR value MATCHES "NOTFOUND$" OR value MATCHES ";")
      continue()
    endif()
    if(value MATCHES "[/\\]lib[/\\]windows_[A-Za-z0-9_]+[/\\]" AND NOT EXISTS "${value}")
      unset("${variable}" CACHE)
      math(EXPR cleared "${cleared} + 1")
    endif()
  endforeach()
  if(cleared GREATER 0)
    message(STATUS "Cleared ${cleared} cached library paths that no longer exist; rediscovering")
  endif()
endfunction()

mixar_clear_missing_library_cache()
