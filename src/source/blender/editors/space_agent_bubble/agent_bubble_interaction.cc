/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_bubble_intern.hh"

namespace blender {

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
