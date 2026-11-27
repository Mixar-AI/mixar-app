/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Mixar: a release hook for IDProperty structs (mixar-backend#2031).
 *
 * The Python ID-property API wraps raw `IDProperty *` pointers. The listener is told the address
 * of every IDProperty struct just before its memory is released or moved (a freed property, a
 * freed group child, an element of a freed or resized IDP_IDPARRAY), so wrappers of that address
 * can be invalidated instead of reading freed memory. The listener may run on any thread and
 * must not dereference the pointer.
 */

#pragma once

namespace blender {

struct IDProperty;

/** Install (or clear, with nullptr) the single release listener. */
void BKE_idprop_mixar_release_listener_set(void (*listener)(const IDProperty *prop));

}  // namespace blender
