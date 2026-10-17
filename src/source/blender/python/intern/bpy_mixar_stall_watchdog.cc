/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pythonintern
 *
 * The main loop's heartbeat for the Python stall watchdog
 * (`mixar/modules/common/utils/stall_watchdog.py`): a counter the window manager bumps
 * every `WM_main` iteration, readable from a worker thread. Registered on the `aud`
 * module next to the capture functions because that module already carries Mixar's
 * native helpers (`bpy_audaspace.cc`).
 */

#include <Python.h>

#include "WM_stall_monitor.hh"

namespace blender {

static PyObject *main_loop_iteration(PyObject * /*self*/, PyObject * /*args*/)
{
  return PyLong_FromUnsignedLongLong(Mixar_stall_iteration_count());
}

static PyMethodDef methods[] = {
    {"_mixar_main_loop_iteration",
     main_loop_iteration,
     METH_NOARGS,
     "Main-loop iterations since startup; unchanged while the main thread is stalled."},
    {nullptr, nullptr, 0, nullptr},
};

void mixar_stall_watchdog_register(PyObject *module)
{
  PyModule_AddFunctions(module, methods);
}

}  // namespace blender
