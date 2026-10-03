/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/** \file
 * \ingroup bke
 *
 * Mixar per-tab undo: what ``undo_tabs.cc``, ``undo_tabs_owner_map.cc`` and
 * ``undo_tabs_partial.cc`` share and nothing else needs.
 */

#include <cstdint>
#include <string>

#include "BLI_map.hh"
#include "BLI_vector.hh"

namespace blender {

struct UndoOwnerMap {
  Map<uint32_t, uint32_t> owner;
  /** The tabs that reach each shared datablock (review 2026-09-30, finding 1:
   * sharing is judged per pressing tab, not across the document). */
  Map<uint32_t, Vector<uint32_t>> shared_by;
  /** Name of each LOCAL shared datablock, the ones a restore could change. */
  Map<uint32_t, std::string> shared_name;
  /** Its ID code (ID_OB, ID_MA, ...): a datablock gone from the live document has
   * no ID left to ask. */
  Map<uint32_t, short> shared_type;
  Vector<std::string> shared_names;
  int shared = 0;
  double build_ms = 0.0;
};

/** The local shared datablocks the tab itself reaches: the ones a restore of
 * this tab would change under another tab. A datablock two OTHER tabs share
 * is none of this tab's business. Returns the count; names up to eight. */
int undo_tabs_owner_map_shared_for_tab(const UndoOwnerMap *map, uint32_t tab, std::string *r_names);

}  // namespace blender
