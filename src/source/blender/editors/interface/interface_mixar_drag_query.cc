/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar: one question the interface module can answer and its callers cannot —
 * is the press the caller is about to claim already spoken for by a button
 * that is waiting to start a drag? #Button is private to this module, so the
 * check has to live here.
 */

#include "UI_interface_c.hh"

#include "interface_intern.hh"
#include "interface_mixar_drag_query.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

bool UI_mixar_region_active_but_is_draggable(ARegion *region)
{
  if (region == nullptr) {
    return false;
  }
  /* The genuinely active button, the way #ui_region_handler finds it — NOT
   * #region_active_but_get, which falls back to #BUT_LAST_ACTIVE and so
   * would keep naming a tile long after the cursor left it. */
  const ui::Button *but = ui::region_find_active_but(region);
  return but != nullptr && ui::button_drag_is_draggable(but);
}

}  // namespace blender
