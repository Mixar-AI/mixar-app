/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "BLI_utildefines.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "WM_api.hh"
#include "WM_mixar.hh"
#include "WM_types.hh"

#include "UI_interface_c.hh"

#include "../interface/interface_intern.hh"

#include "agent_bubble_intern.hh"

namespace blender {

/* Switching Zen / Engine is app chrome, not leaving the chat: a press on the
 * topbar Zen/Engine slider keeps the island open. It used to collapse it
 * mid-turn, and the collapse hid the island behind the main window for about
 * 0.3 s before the pill appeared. Only buttons in the pressed area's regions are
 * seen here: an item in a popup menu would not be (the old "Zen Mode / Engine
 * Mode" menu is dormant, `mode_menu.py`). */
static bool agent_bubble_press_hits_mode_switch(bContext *C, const wmEvent *event)
{
  const ARegion *region = CTX_wm_region(C);
  if (region == nullptr) {
    return false;
  }
  const ui::Button *but = ui::but_find_mouse_over(region, event);
  return but != nullptr && but->optype != nullptr &&
         STRPREFIX(but->optype->idname, "MIXAR_OT_set_ui_mode_");
}

bool agent_bubble_should_dismiss(bContext *C, const wmEvent *event, void *bubble, void *pill)
{
  const wmWindow *target = CTX_wm_window(C);
  if (!target || event->val != KM_PRESS ||
      !ELEM(event->type, LEFTMOUSE, MIDDLEMOUSE, RIGHTMOUSE) ||
      ELEM(target->runtime->ghostwin, bubble, pill))
  {
    return false;
  }
  /* A press inside a temporary window (picker, render view, Preferences) is
   * interaction with that window, not an outside click. */
  if (WM_window_is_temp_screen(target)) {
    return false;
  }
  /* While a modal dialog hides the island (splash, close-file, a
   * `mixar_invoke_modal_dialog`), presses belong to that dialog: collapsing
   * the hidden island here would bring it back minimised instead of as it was
   * (wm_mixar_modal_dialog.cc). */
  if (Mixar_floating_docks_held()) {
    return false;
  }
  if (agent_bubble_press_hits_mode_switch(C, event)) {
    return false;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  const wmWindow *bubble_win = nullptr;
  for (const wmWindow &win : wm->windows) {
    if (win.runtime->ghostwin == bubble) {
      bubble_win = &win;
      break;
    }
  }
  for (wmWindow &win : wm->windows) {
    const bool is_island = ELEM(win.runtime->ghostwin, bubble, pill);
    const bScreen *screen = WM_window_get_active_screen(&win);
    /* Pickers belong to the chat interaction even outside its frame: the file
     * dialog the island opens is parented to it, so hiding the island would
     * take the picker down. Any file picker anywhere is treated the same.
     * Other temporary windows elsewhere (an open Preferences window, a render
     * view) must NOT freeze the collapse. */
    if (!is_island && WM_window_is_temp_screen(&win)) {
      if (bubble_win && win.parent == bubble_win) {
        return false;
      }
      if (screen) {
        for (const ScrArea &area : screen->areabase) {
          if (area.spacetype == SPACE_FILE) {
            return false;
          }
        }
      }
    }
    if (!screen) {
      continue;
    }
    for (const ScrArea &area : screen->areabase) {
      if (area.spacetype == SPACE_FILE && area.full != nullptr) {
        return false;
      }
    }
    if (win.runtime->ghostwin == bubble && !BLI_listbase_is_empty(&screen->regionbase)) {
      return false;
    }
  }
  return true;
}

}  // namespace blender
