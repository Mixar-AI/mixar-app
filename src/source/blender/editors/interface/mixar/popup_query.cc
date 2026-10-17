/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * Whether a window has a pop-up block open (`Window.mixar_popup_block_open`).
 *
 * Every pop-up block — menu, popover (keep-open included), search menu, pie,
 * props dialog, confirmation — lives in a temporary region of the window's
 * `screen->regionbase` and is driven by a window modal UI handler
 * (`popup_handler`, or `handler_region_menu` while a button holds its menu
 * open). Both handlers "block all events, this is modal interaction": only a
 * drop or a double click continues past them. A Python window modal started
 * AFTER the pop-up opened sits ahead of that handler (`wm_handler_operator_insert`
 * adds at the head), so it sees the pop-up's own clicks and keys first; the
 * agent viewport lock asks this to yield to the pop-up rather than eat them.
 *
 * Tooltips are temporary regions too but carry no block, and a block only
 * has a `handle` while a pop-up owns it, so neither counts.
 */

#include "../interface_intern.hh"

#include "BLI_listbase_iterator.hh"

#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "WM_api.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

bool Mixar_window_popup_block_open(wmWindow *win)
{
  bScreen *screen = win ? WM_window_get_active_screen(win) : nullptr;
  if (screen == nullptr) {
    return false;
  }
  for (ARegion &region : screen->regionbase) {
    if (region.runtime == nullptr) {
      continue;
    }
    for (ui::Block &block : region.runtime->uiblocks) {
      if (block.handle != nullptr) {
        return true;
      }
    }
  }
  return false;
}

}  // namespace blender
