/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup pygen
 *
 * Mixar: invalidation of Python ID-property wrappers whose property was freed
 * (mixar-backend#2031).
 *
 * `obj["group"]`, its arrays and `id_properties_ui()` managers hold raw `IDProperty *`
 * pointers. Upstream leaves them dangling when the property is deleted, replaced or popped, so
 * a script that kept one and used it later read or wrote freed memory. Each wrapper registers
 * the field that holds its pointer; the IDProperty release hook (`BKE_idprop_mixar.hh`) clears
 * that field, and every accessor raises `ReferenceError` on a cleared one.
 */

#pragma once

#include <Python.h>

namespace blender {

struct IDProperty;

/** Install the IDProperty release listener (once, at Python start-up). */
void BPy_IDProperty_liveness_init();
/** Clear `*slot` when the property it points to is released. A null `*slot` is ignored. */
void BPy_IDProperty_liveness_track(IDProperty **slot);
/** Stop tracking `slot` (wrapper deallocation). Safe after the slot was cleared. */
void BPy_IDProperty_liveness_untrack(IDProperty **slot);
/** Set `ReferenceError` for a wrapper whose property was removed; returns nullptr. */
PyObject *BPy_IDProperty_raise_removed();

}  // namespace blender

/** Guard a wrapper's property pointer at the top of an accessor. */
#define BPY_IDPROP_CHECK_OBJ(prop) \
  if (UNLIKELY((prop) == nullptr)) { \
    return BPy_IDProperty_raise_removed(); \
  } \
  ((void)0)

#define BPY_IDPROP_CHECK_INT(prop) \
  if (UNLIKELY((prop) == nullptr)) { \
    BPy_IDProperty_raise_removed(); \
    return -1; \
  } \
  ((void)0)
