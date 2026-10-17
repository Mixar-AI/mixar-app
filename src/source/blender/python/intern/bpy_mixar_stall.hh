/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pythonintern
 *
 * Names a Python callable for the main-thread stall monitor's breadcrumbs
 * (`WM_stall_monitor.hh`): `module.qualname`, a `functools.partial` by its
 * wrapped function, anything else by its type name. Cheap enough to run per
 * timer tick: two attribute reads, no allocation beyond the temporaries.
 */

#pragma once

#include <Python.h>

#include "BLI_string.h"

namespace blender {

inline void bpy_mixar_stall_callable_name_compute(PyObject *callable, char *r_name, size_t len)
{
  PyObject *target = callable;
  const char *prefix = "";
  PyObject *func_attr = nullptr;
  if (!PyObject_HasAttrString(callable, "__qualname__") &&
      PyObject_HasAttrString(callable, "func"))
  {
    func_attr = PyObject_GetAttrString(callable, "func");
    if (func_attr) {
      target = func_attr;
      prefix = "partial:";
    }
  }
  PyObject *qualname = PyObject_GetAttrString(target, "__qualname__");
  PyObject *module = PyObject_GetAttrString(target, "__module__");
  const char *qualname_str = (qualname && PyUnicode_Check(qualname)) ? PyUnicode_AsUTF8(qualname) :
                                                                       nullptr;
  const char *module_str = (module && PyUnicode_Check(module)) ? PyUnicode_AsUTF8(module) :
                                                                 nullptr;
  if (qualname_str) {
    BLI_snprintf(r_name, len, "%s%s.%s", prefix, module_str ? module_str : "?", qualname_str);
  }
  else {
    BLI_snprintf(r_name, len, "%s%s", prefix, Py_TYPE(target)->tp_name);
  }
  PyErr_Clear();
  Py_XDECREF(qualname);
  Py_XDECREF(module);
  Py_XDECREF(func_attr);
}

/**
 * Cached by callable: timers and draw handlers run many times a second and the
 * attribute reads were 0.5% of an idle main thread. Each cached entry holds a
 * reference so the address cannot be reused by another function while cached;
 * a full cache is dropped wholesale (64 entries cover every registered tick).
 */
inline void bpy_mixar_stall_callable_name(PyObject *callable, char *r_name, size_t len)
{
  constexpr int CACHE_MAX = 64;
  constexpr int ENTRY_NAME_LEN = 96;
  struct Entry {
    PyObject *callable;
    char name[ENTRY_NAME_LEN];
  };
  static Entry cache[CACHE_MAX];
  static int cache_num = 0;

  for (int i = 0; i < cache_num; i++) {
    if (cache[i].callable == callable) {
      BLI_strncpy(r_name, cache[i].name, len);
      return;
    }
  }
  if (cache_num == CACHE_MAX) {
    for (int i = 0; i < cache_num; i++) {
      Py_DECREF(cache[i].callable);
    }
    cache_num = 0;
  }
  Entry &entry = cache[cache_num++];
  entry.callable = callable;
  Py_INCREF(callable);
  bpy_mixar_stall_callable_name_compute(callable, entry.name, sizeof(entry.name));
  BLI_strncpy(r_name, entry.name, len);
}

}  // namespace blender
