/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include <cstdint>

/* Recover missing flagsChanged events from the next native event's snapshot.
 * The caller supplies Cocoa's Shift/Control/Option/Command masks and emits
 * ordinary GHOST modifier events before delivering the triggering input. */
template<typename Emit>
bool mixar_cocoa_modifier_changes(const uint32_t previous,
                                 const uint32_t current,
                                 const uint32_t (&masks)[4],
                                 Emit emit)
{
  bool changed = false;
  for (int index = 0; index < 4; index++) {
    if ((previous & masks[index]) != (current & masks[index])) {
      emit(index, (current & masks[index]) != 0);
      changed = true;
    }
  }
  return changed;
}
