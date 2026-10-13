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
