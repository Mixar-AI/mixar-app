/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pythonintern
 *
 * The install directory is read-only at runtime: Python's bytecode cache goes
 * to a per-user cache directory, never into `__pycache__` beside the bundled
 * sources. A file written into the signed macOS bundle breaks its code
 * signature, and Gatekeeper then refuses to open the app ("Mixar is damaged");
 * a per-machine Windows install cannot be written at all, so it recompiled
 * every module on every launch.
 *
 * - This process: `PyConfig.pycache_prefix`, set before Python starts, because
 *   the standard library is imported before any startup script runs.
 * - Plain child Pythons (`sys.executable`): `PYTHONPYCACHEPREFIX` is exported.
 * - Isolated child Pythons (`sys.executable` + `bpy.app.python_args`, which
 *   carries `-I` and so hides that variable): `-X pycache_prefix=<dir>`.
 */

#pragma once

#include <Python.h>

#include <string>

#include "BKE_appdir.hh"

#include "BLI_path_utils.hh"

namespace blender {

/** Names the cache root for this process and for child Pythons. */
inline constexpr const char *BPY_MIXAR_PYCACHE_ENV = "PYTHONPYCACHEPREFIX";

/**
 * Point `config` at the bytecode cache before #Py_InitializeFromConfig.
 *
 * An inherited `PYTHONPYCACHEPREFIX` wins (a parent Mixar process, or a test,
 * already chose one); otherwise `<user caches>/pycache`, e.g.
 * `~/Library/Caches/Mixar/pycache`. With no usable directory, bytecode is not
 * written at all rather than written into the install directory.
 */
inline PyStatus bpy_mixar_pycache_config(PyConfig *config)
{
  std::string prefix;
  const char *inherited = BLI_getenv(BPY_MIXAR_PYCACHE_ENV);
  if (inherited && inherited[0] && BLI_path_is_abs_from_cwd(inherited)) {
    prefix = inherited;
  }
  else {
    char caches[FILE_MAX];
    BKE_appdir_folder_caches(caches, sizeof(caches));
    if (caches[0] && BLI_path_is_abs_from_cwd(caches)) {
      char path[FILE_MAX];
      BLI_path_join(path, sizeof(path), caches, "pycache");
      prefix = path;
    }
  }
  if (prefix.empty()) {
    config->write_bytecode = 0;
    return PyStatus_Ok();
  }
  BLI_setenv(BPY_MIXAR_PYCACHE_ENV, prefix.c_str());
  return PyConfig_SetBytesString(config, &config->pycache_prefix, prefix.c_str());
}

/**
 * The `bpy.app.python_args` entries that give a child Python this process's
 * bytecode rule: `-X pycache_prefix=<dir>`, or `-B` when nothing is written.
 * Writes at most two entries to `r_args`; `r_option` owns the `-X` value.
 */
inline int bpy_mixar_pycache_python_args(std::string &r_option, const char **r_args)
{
  PyObject *prefix = PySys_GetObject("pycache_prefix"); /* Borrowed. */
  if (prefix && PyUnicode_Check(prefix)) {
    const char *prefix_str = PyUnicode_AsUTF8(prefix);
    if (prefix_str) {
      r_option = std::string("pycache_prefix=") + prefix_str;
      r_args[0] = "-X";
      r_args[1] = r_option.c_str();
      return 2;
    }
    PyErr_Clear();
  }
  PyObject *dont_write = PySys_GetObject("dont_write_bytecode"); /* Borrowed. */
  if (dont_write && PyObject_IsTrue(dont_write) == 1) {
    r_args[0] = "-B";
    return 1;
  }
  return 0;
}

}  // namespace blender
